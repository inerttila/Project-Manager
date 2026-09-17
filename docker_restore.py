import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

DEFAULT_PG_IMAGE = 'postgres:18'
DEFAULT_PG_USER = 'openpg'
DEFAULT_PG_PASSWORD = 'openpgpwd'
HOST_PORT = 5435
DOCKER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'docker_instances')

if os.name == 'nt':
    CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW
else:
    CREATE_NO_WINDOW = 0


def validate_db_name(db_name):
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', db_name or ''):
        raise ValueError('Database name must contain only letters, numbers, and underscores')
    # PostgreSQL folds unquoted identifiers to lowercase, but psql -d uses the
    # connection name as-is. Normalize so CREATE DATABASE and psql -d match.
    return db_name.lower()


def container_name_for_db(db_name):
    return f'{validate_db_name(db_name)}-postgres'


def volume_name_for_db(db_name):
    return f'{validate_db_name(db_name)}_postgres_data'


def compose_project_for_db(db_name):
    return f'{validate_db_name(db_name)}-postgres'


def instance_dir_for_db(db_name):
    return os.path.join(DOCKER_DIR, validate_db_name(db_name))


def run_command(cmd, timeout=900, cwd=None):
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
        creationflags=CREATE_NO_WINDOW,
    )


def run_command_stream(cmd, log, timeout=900, cwd=None):
    log(f'$ {" ".join(cmd)}')
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=cwd,
        creationflags=CREATE_NO_WINDOW,
    )
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            cleaned = line.rstrip()
            if cleaned:
                log(cleaned)
        return proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        proc.kill()
        raise RuntimeError('Command timed out') from exc


def pick_backup_path(mode='file'):
    """Open a native OS dialog and return the selected path, or None if cancelled."""
    mode = 'folder' if mode == 'folder' else 'file'
    script = (
        'import sys\n'
        'import tkinter as tk\n'
        'from tkinter import filedialog\n'
        'root = tk.Tk()\n'
        'root.withdraw()\n'
        'root.attributes("-topmost", True)\n'
        'mode = sys.argv[1] if len(sys.argv) > 1 else "file"\n'
        'if mode == "folder":\n'
        '    path = filedialog.askdirectory(title="Select backup folder")\n'
        'else:\n'
        '    path = filedialog.askopenfilename(\n'
        '        title="Select backup zip",\n'
        '        filetypes=[("Zip files", "*.zip"), ("All files", "*.*")],\n'
        '    )\n'
        'print(path or "", end="")\n'
        'root.destroy()\n'
    )
    result = subprocess.run(
        [sys.executable, '-c', script, mode],
        capture_output=True,
        text=True,
        timeout=300,
    )
    path = (result.stdout or '').strip()
    if not path:
        return None
    return os.path.normpath(path)


def _is_zip_backup(path):
    return os.path.isfile(path) and path.lower().endswith('.zip')


def _read_manifest_db_name(manifest_path):
    if not os.path.isfile(manifest_path):
        return None
    try:
        with open(manifest_path, 'r', encoding='utf-8') as handle:
            manifest = json.load(handle)
        return manifest.get('db_name') or None
    except Exception:
        return None


def _backup_info_from_dir(backup_dir, original_path, db_name_hint=None):
    dump_file = os.path.join(backup_dir, 'dump.sql')
    if not os.path.isfile(dump_file):
        raise ValueError('dump.sql not found in backup')

    db_name = db_name_hint or os.path.basename(backup_dir.rstrip('\\/'))
    manifest_db_name = _read_manifest_db_name(os.path.join(backup_dir, 'manifest.json'))
    if manifest_db_name:
        db_name = manifest_db_name

    db_name = validate_db_name(db_name)
    filestore_source = os.path.join(backup_dir, 'filestore')
    return {
        'backup_path': original_path,
        'dump_file': dump_file,
        'db_name': db_name,
        'has_filestore': os.path.isdir(filestore_source),
        'filestore_source': filestore_source if os.path.isdir(filestore_source) else None,
        'container_name': container_name_for_db(db_name),
        'port': HOST_PORT,
    }


def _zip_dump_entry(names):
    """Return the shallowest dump.sql path inside a zip namelist."""
    dumps = [
        name.replace('\\', '/')
        for name in names
        if not name.endswith('/') and os.path.basename(name.replace('\\', '/')) == 'dump.sql'
    ]
    if not dumps:
        raise ValueError('dump.sql not found in zip backup')
    dumps.sort(key=lambda name: name.count('/'))
    return dumps[0]


def _zip_root_prefix(dump_entry):
    dump_entry = dump_entry.replace('\\', '/')
    if dump_entry == 'dump.sql':
        return ''
    parts = dump_entry.split('/')
    if len(parts) != 2:
        raise ValueError('dump.sql must be at the zip root or inside a single top-level folder')
    return parts[0] + '/'


def _detect_zip_backup_info(zip_path):
    try:
        with zipfile.ZipFile(zip_path, 'r') as archive:
            names = [name.replace('\\', '/') for name in archive.namelist()]
            dump_entry = _zip_dump_entry(names)
            root_prefix = _zip_root_prefix(dump_entry)

            if root_prefix:
                db_name = root_prefix.rstrip('/')
            else:
                db_name = os.path.splitext(os.path.basename(zip_path))[0]

            manifest_entry = f'{root_prefix}manifest.json'
            if manifest_entry in names:
                try:
                    with archive.open(manifest_entry) as handle:
                        manifest = json.load(handle)
                    if manifest.get('db_name'):
                        db_name = manifest['db_name']
                except Exception:
                    pass

            has_filestore = any(
                name == f'{root_prefix}filestore'
                or name.startswith(f'{root_prefix}filestore/')
                for name in names
            )
    except zipfile.BadZipFile as exc:
        raise ValueError('Invalid or corrupted zip backup') from exc

    db_name = validate_db_name(db_name)
    return {
        'backup_path': zip_path,
        'dump_file': None,
        'db_name': db_name,
        'has_filestore': has_filestore,
        'filestore_source': None,
        'container_name': container_name_for_db(db_name),
        'port': HOST_PORT,
    }


def _resolve_extracted_backup_dir(extract_root):
    dump_file = os.path.join(extract_root, 'dump.sql')
    if os.path.isfile(dump_file):
        return extract_root

    entries = [
        entry for entry in os.listdir(extract_root)
        if entry not in ('.', '..') and not entry.startswith('__MACOSX')
    ]
    if len(entries) == 1:
        nested = os.path.join(extract_root, entries[0])
        if os.path.isdir(nested) and os.path.isfile(os.path.join(nested, 'dump.sql')):
            return nested

    raise ValueError('dump.sql not found in zip backup')


def extract_zip_backup(zip_path, log=None):
    """Extract a zip backup. Returns (backup_dir, cleanup_dir, db_name_hint)."""
    zip_path = os.path.normpath(zip_path)
    if not _is_zip_backup(zip_path):
        raise ValueError('Backup path is not a zip file')

    extract_root = tempfile.mkdtemp(prefix='gpm_restore_')
    try:
        if log:
            log(f'Extracting zip backup: {zip_path}')
        with zipfile.ZipFile(zip_path, 'r') as archive:
            archive.extractall(extract_root)

        backup_dir = _resolve_extracted_backup_dir(extract_root)
        if backup_dir == extract_root:
            db_name_hint = os.path.splitext(os.path.basename(zip_path))[0]
        else:
            db_name_hint = os.path.basename(backup_dir)

        if log:
            log('Zip extraction completed.')
        return backup_dir, extract_root, db_name_hint
    except Exception:
        shutil.rmtree(extract_root, ignore_errors=True)
        raise


def detect_backup_info(backup_path):
    backup_path = os.path.normpath(backup_path)

    if _is_zip_backup(backup_path):
        return _detect_zip_backup_info(backup_path)

    if not os.path.isdir(backup_path):
        raise ValueError('Backup path must be a folder or .zip file')

    return _backup_info_from_dir(
        backup_path,
        original_path=backup_path,
        db_name_hint=os.path.basename(backup_path.rstrip('\\/')),
    )


def container_exists(container_name):
    result = run_command(['docker', 'ps', '-a', '--filter', f'name=^{container_name}$', '--format', '{{.Names}}'])
    return container_name in (result.stdout or '').splitlines()


def container_is_running(container_name):
    result = run_command(['docker', 'ps', '--filter', f'name=^{container_name}$', '--format', '{{.Names}}'])
    return container_name in (result.stdout or '').splitlines()


def get_container_on_port(port):
    result = run_command(['docker', 'ps', '--format', '{{.Names}}|{{.Ports}}'])
    needle = f':{port}->'
    for line in (result.stdout or '').splitlines():
        if '|' not in line:
            continue
        name, ports = line.split('|', 1)
        if needle in ports:
            return name.strip()
    return None


def raise_port_busy(port, holder_container, log):
    log(f'ERROR: Port {port} is busy (used by container "{holder_container}").')
    log(f'Stop that container manually, then run the restore again.')
    raise RuntimeError(f'Port {port} is busy (container: {holder_container})')


def ensure_compose_file(db_name, container_name):
    instance_dir = instance_dir_for_db(db_name)
    os.makedirs(instance_dir, exist_ok=True)
    volume_name = volume_name_for_db(db_name)
    compose_path = os.path.join(instance_dir, 'docker-compose.yml')
    content = f"""services:
  postgres:
    image: {DEFAULT_PG_IMAGE}
    container_name: {container_name}
    restart: unless-stopped
    environment:
      POSTGRES_USER: {DEFAULT_PG_USER}
      POSTGRES_PASSWORD: {DEFAULT_PG_PASSWORD}
      POSTGRES_DB: {db_name}
      POSTGRES_INITDB_ARGS: "--locale=en_US.UTF-8 --encoding=UTF8"
      LANG: en_US.UTF-8
      LC_ALL: en_US.UTF-8
    ports:
      - "{HOST_PORT}:5432"
    volumes:
      - {volume_name}:/var/lib/postgresql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U {DEFAULT_PG_USER} -d {db_name}"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  {volume_name}:
    name: {volume_name}
"""
    with open(compose_path, 'w', encoding='utf-8') as handle:
        handle.write(content)
    return compose_path, instance_dir


def pull_postgres_image(log):
    log('Pulling latest PostgreSQL image (postgres:18)...')
    returncode = run_command_stream(['docker', 'pull', DEFAULT_PG_IMAGE], log, timeout=900)
    if returncode != 0:
        raise RuntimeError('Failed to pull postgres image')
    log('PostgreSQL image is up to date.')


def wait_for_healthy(container_name, log, retries=45):
    log(f'Waiting for container {container_name} to become healthy...')
    while retries > 0:
        result = run_command(['docker', 'inspect', '--format', '{{.State.Health.Status}}', container_name], timeout=20)
        status = (result.stdout or '').strip()
        if status == 'healthy':
            log('Container is healthy.')
            return
        if status == 'unhealthy':
            raise RuntimeError(f'Container {container_name} is unhealthy')
        time.sleep(2)
        retries -= 1
    raise RuntimeError(f'Container {container_name} did not become healthy in time')


def ensure_container(info, log):
    db_name = info['db_name']
    container_name = info['container_name']
    ensure_compose_file(db_name, container_name)
    instance_dir = instance_dir_for_db(db_name)
    port_holder = get_container_on_port(HOST_PORT)

    if container_is_running(container_name):
        log(f'Using running container {container_name} on port {HOST_PORT}.')
        wait_for_healthy(container_name, log)
        return

    if container_exists(container_name):
        if port_holder and port_holder != container_name:
            raise_port_busy(HOST_PORT, port_holder, log)
        log(f'Starting existing container {container_name}...')
        result = run_command(['docker', 'start', container_name], timeout=120)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or 'Failed to start container')
    else:
        if port_holder:
            raise_port_busy(HOST_PORT, port_holder, log)
        log(f'Creating Postgres container {container_name} on port {HOST_PORT}...')
        result = run_command(
            ['docker', 'compose', '-p', compose_project_for_db(db_name), 'up', '-d'],
            cwd=instance_dir,
            timeout=300,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or 'Failed to start docker compose')

    wait_for_healthy(container_name, log)


def restore_database(info, log):
    db_name = info['db_name']
    container_name = info['container_name']

    log(f'Recreating database {db_name}...')
    run_command([
        'docker', 'exec', container_name, 'psql', '-U', DEFAULT_PG_USER, '-d', 'postgres', '-c',
        f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{db_name}' AND pid <> pg_backend_pid();",
    ], timeout=120)

    for sql in [
        f'DROP DATABASE IF EXISTS {db_name} WITH (FORCE);',
        (
            f"CREATE DATABASE {db_name} OWNER {DEFAULT_PG_USER} "
            "ENCODING 'UTF8' LC_COLLATE='en_US.UTF-8' LC_CTYPE='en_US.UTF-8' TEMPLATE template0;"
        ),
    ]:
        result = run_command(['docker', 'exec', container_name, 'psql', '-U', DEFAULT_PG_USER, '-d', 'postgres', '-c', sql], timeout=300)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or '').strip()
            raise RuntimeError(detail or 'Failed to recreate database')

    log('Copying dump into container...')
    copy_result = run_command(['docker', 'cp', info['dump_file'], f'{container_name}:/tmp/restore_dump.sql'], timeout=600)
    if copy_result.returncode != 0:
        raise RuntimeError(copy_result.stderr.strip() or 'Failed to copy dump into container')

    log('Restoring SQL dump (this may take a few minutes)...')
    restore_result = run_command([
        'docker', 'exec', container_name, 'psql', '-U', DEFAULT_PG_USER, '-d', db_name,
        '-v', 'ON_ERROR_STOP=1', '-f', '/tmp/restore_dump.sql',
    ], timeout=1800)
    if restore_result.returncode != 0:
        raise RuntimeError(restore_result.stderr.strip() or 'Database restore failed')

    run_command(['docker', 'exec', container_name, 'rm', '/tmp/restore_dump.sql'], timeout=60)
    log('Database restore completed.')


def copy_filestore(info, odoo_sessions_dir, log):
    if not info.get('filestore_source'):
        log('No filestore folder found. Skipping filestore copy.')
        return None

    target = os.path.join(odoo_sessions_dir, 'filestore', info['db_name'])
    os.makedirs(os.path.dirname(target), exist_ok=True)
    if os.path.exists(target):
        shutil.rmtree(target)
    shutil.copytree(info['filestore_source'], target)
    log(f'Filestore copied to {target}')
    return target


def restore_docker_database(backup_path, db_name=None, odoo_sessions_dir=None, log_callback=None):
    logs = []
    cleanup_dir = None

    def log(message):
        logs.append(message)
        if log_callback:
            log_callback(message)

    try:
        backup_path = os.path.normpath(backup_path)
        if _is_zip_backup(backup_path):
            backup_dir, cleanup_dir, db_name_hint = extract_zip_backup(backup_path, log)
            info = _backup_info_from_dir(
                backup_dir,
                original_path=backup_path,
                db_name_hint=db_name_hint,
            )
        else:
            info = detect_backup_info(backup_path)

        if db_name:
            info['db_name'] = validate_db_name(db_name.strip())
            info['container_name'] = container_name_for_db(info['db_name'])

        pull_postgres_image(log)
        ensure_container(info, log)
        restore_database(info, log)

        filestore_target = None
        if odoo_sessions_dir:
            filestore_target = copy_filestore(info, odoo_sessions_dir, log)

        result = {
            'db_name': info['db_name'],
            'container_name': info['container_name'],
            'port': HOST_PORT,
            'host': 'localhost',
            'db_user': DEFAULT_PG_USER,
            'db_password': DEFAULT_PG_PASSWORD,
            'filestore_target': filestore_target,
            'logs': logs,
        }
        log(
            f"Done. Postgres: localhost:{HOST_PORT} | database: {info['db_name']} | container: {info['container_name']}"
        )
        return result
    finally:
        if cleanup_dir:
            shutil.rmtree(cleanup_dir, ignore_errors=True)
