from flask import Flask, request, jsonify, send_from_directory, Response, stream_with_context
from flask_cors import CORS
import os
import json
import subprocess
import platform
import queue
import threading
from pathlib import Path

from docker_restore import detect_backup_info, restore_docker_database
from git_stream import run_git_status, run_git_checkout, run_git_pull

if platform.system() == 'Windows':
    CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW
    CREATE_NEW_CONSOLE = 0x00000010
else:
    CREATE_NO_WINDOW = 0
    CREATE_NEW_CONSOLE = 0

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, 'static')

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path='/static')
CORS(app)

PROJECTS_FILE = 'projects.json'
SETTINGS_FILE = 'settings.json'

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}

def save_settings(settings):
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, indent=2)

def load_projects():
    if os.path.exists(PROJECTS_FILE):
        with open(PROJECTS_FILE, 'r') as f:
            return json.load(f)
    return []

def save_projects(projects):
    with open(PROJECTS_FILE, 'w') as f:
        json.dump(projects, f, indent=2)

def get_project_name(path):
    return os.path.basename(path.rstrip('/\\'))

def get_git_remote_url(project_path):
    if not os.path.exists(project_path):
        return None
    
    try:
        result = subprocess.run(
            ['git', 'remote', 'get-url', 'origin'],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=CREATE_NO_WINDOW
        )
        
        if result.returncode != 0:
            result = subprocess.run(
                ['git', 'remote', '-v'],
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=CREATE_NO_WINDOW
            )
            if result.returncode == 0 and result.stdout:
                lines = result.stdout.strip().split('\n')
                if lines:
                    parts = lines[0].split()
                    if len(parts) >= 2:
                        remote_url = parts[1]
                    else:
                        return None
                else:
                    return None
            else:
                return None
        else:
            remote_url = result.stdout.strip()
        
        if remote_url.startswith('git@'):
            remote_url = remote_url.replace('git@', 'https://').replace(':', '/')
            if remote_url.endswith('.git'):
                remote_url = remote_url[:-4]
        elif remote_url.startswith('http'):
            if remote_url.endswith('.git'):
                remote_url = remote_url[:-4]
        else:
            return None
        
        return remote_url
        
    except (subprocess.TimeoutExpired, Exception):
        return None

@app.route('/')
def index():
    return send_from_directory(STATIC_DIR, 'index.html')

@app.route('/api/projects', methods=['GET'])
def get_projects():
    projects = load_projects()
    valid_projects = []
    updated = False
    
    for project in projects:
        if os.path.exists(project['path']):
            project_data = {
                'path': project['path'],
                'name': get_project_name(project['path'])
            }
            if 'git_remote_url' in project:
                project_data['git_remote_url'] = project['git_remote_url']
            project_data['links'] = project.get('links', []) if isinstance(project.get('links'), list) else []
            valid_projects.append(project_data)
        else:
            updated = True
    if updated:
        save_projects(valid_projects)
    return jsonify(valid_projects)

@app.route('/api/projects', methods=['POST'])
def add_project():
    data = request.json
    path = data.get('path', '').strip()

    if not path:
        return jsonify({'error': 'Path is required'}), 400
    
    path = os.path.normpath(path)
    
    if not os.path.exists(path):
        return jsonify({'error': 'Path does not exist'}), 400
    
    if not os.path.isdir(path):
        return jsonify({'error': 'Path must be a directory'}), 400
    
    projects = load_projects()
    
    if any(p['path'] == path for p in projects):
        return jsonify({'error': 'Project already exists'}), 400
    
    git_remote_url = get_git_remote_url(path)
    
    project_data = {'path': path}
    if git_remote_url:
        project_data['git_remote_url'] = git_remote_url
    
    projects.append(project_data)
    save_projects(projects)
    
    response_data = {
        'path': path,
        'name': get_project_name(path)
    }
    if git_remote_url:
        response_data['git_remote_url'] = git_remote_url
    
    return jsonify(response_data), 201

@app.route('/api/projects/clone', methods=['POST'])
def clone_project():
    data = request.json
    clone_path = data.get('clone_path', '').strip()
    repository_url = data.get('repository_url', '').strip()
    
    if not clone_path:
        return jsonify({'error': 'Clone path is required'}), 400
    
    if not repository_url:
        return jsonify({'error': 'Repository URL is required'}), 400
    
    clone_path = os.path.normpath(clone_path)
    
    if not os.path.exists(clone_path):
        return jsonify({'error': 'Clone path does not exist'}), 400
    
    if not os.path.isdir(clone_path):
        return jsonify({'error': 'Clone path must be a directory'}), 400
    
    repo_name = repository_url.rstrip('/').split('/')[-1]
    if repo_name.endswith('.git'):
        repo_name = repo_name[:-4]
    
    project_path = os.path.join(clone_path, repo_name)
    
    projects = load_projects()
    if any(p['path'] == project_path for p in projects):
        return jsonify({'error': 'Project already exists'}), 400
    
    if os.path.exists(project_path):
        return jsonify({'error': f'Directory {project_path} already exists'}), 400
    
    try:
        result = subprocess.run(
            ['git', 'clone', repository_url, project_path],
            capture_output=True,
            text=True,
            timeout=300,
            creationflags=CREATE_NO_WINDOW
        )
        
        if result.returncode != 0:
            return jsonify({
                'error': 'Failed to clone repository',
                'message': result.stderr
            }), 400
        
        git_remote_url = get_git_remote_url(project_path)
        
        project_data = {'path': project_path}
        if git_remote_url:
            project_data['git_remote_url'] = git_remote_url
        
        projects.append(project_data)
        save_projects(projects)
        
        response_data = {
            'path': project_path,
            'name': get_project_name(project_path)
        }
        if git_remote_url:
            response_data['git_remote_url'] = git_remote_url
        
        return jsonify(response_data), 201
        
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Clone operation timed out'}), 500
    except Exception as e:
        return jsonify({'error': f'Error cloning repository: {str(e)}'}), 500

@app.route('/api/projects/<int:project_id>', methods=['DELETE'])
def delete_project(project_id):
    projects = load_projects()
    
    if project_id < 0 or project_id >= len(projects):
        return jsonify({'error': 'Project not found'}), 404
    
    projects.pop(project_id)
    save_projects(projects)
    
    return jsonify({'message': 'Project deleted'}), 200

@app.route('/api/projects/reorder', methods=['POST'])
def reorder_projects():
    data = request.json or {}
    ordered_paths = data.get('ordered_paths', [])

    if not isinstance(ordered_paths, list) or not all(isinstance(p, str) for p in ordered_paths):
        return jsonify({'error': 'ordered_paths must be a list of strings'}), 400

    projects = load_projects()

    by_path = {p.get('path'): p for p in projects if isinstance(p, dict) and p.get('path')}

    reordered = []
    seen = set()

    for path in ordered_paths:
        proj = by_path.get(path)
        if proj and path not in seen:
            reordered.append(proj)
            seen.add(path)

    for proj in projects:
        path = proj.get('path') if isinstance(proj, dict) else None
        if path and path not in seen:
            reordered.append(proj)
            seen.add(path)

    save_projects(reordered)
    return jsonify({'message': 'Projects reordered'}), 200

@app.route('/api/projects/<int:project_id>/links', methods=['GET', 'PUT'])
def project_links(project_id):
    projects = load_projects()
    if project_id < 0 or project_id >= len(projects):
        return jsonify({'error': 'Project not found'}), 404

    if request.method == 'GET':
        links = projects[project_id].get('links', [])
        if not isinstance(links, list):
            links = []
        return jsonify({'links': links})

    data = request.json or {}
    links = data.get('links', [])
    if not isinstance(links, list):
        return jsonify({'error': 'links must be a list'}), 400
    for item in links:
        if not isinstance(item, dict) or 'name' not in item or 'url' not in item:
            return jsonify({'error': 'Each link must have "name" and "url"'}), 400
    projects[project_id]['links'] = links
    save_projects(projects)
    return jsonify({'links': projects[project_id]['links']})


def _sse_response(event_stream):
    response = Response(stream_with_context(event_stream()), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['X-Accel-Buffering'] = 'no'
    return response


def _queue_event_stream(worker):
    def event_stream():
        log_queue = queue.Queue()

        def run_worker():
            try:
                result = worker(lambda message: log_queue.put(('log', message)))
                log_queue.put(('done', result or {}))
            except Exception as exc:
                log_queue.put(('error', str(exc)))

        threading.Thread(target=run_worker, daemon=True).start()

        while True:
            kind, payload = log_queue.get()
            if kind == 'log':
                yield f"data: {json.dumps({'type': 'log', 'message': payload})}\n\n"
            elif kind == 'done':
                yield f"data: {json.dumps({'type': 'done', 'result': payload})}\n\n"
                break
            elif kind == 'error':
                yield f"data: {json.dumps({'type': 'error', 'message': payload})}\n\n"
                break

    return _sse_response(event_stream)


def _get_project_path(project_id):
    projects = load_projects()
    if project_id < 0 or project_id >= len(projects):
        return None, (jsonify({'error': 'Project not found'}), 404)
    project_path = projects[project_id]['path']
    if not os.path.exists(project_path):
        return None, (jsonify({'error': 'Project path does not exist'}), 404)
    return project_path, None


@app.route('/api/projects/<int:project_id>/git-stream', methods=['POST'])
def git_stream(project_id):
    project_path, error = _get_project_path(project_id)
    if error:
        return error

    data = request.json or {}
    action = (data.get('action') or '').strip()
    branch_name = (data.get('branch') or '').strip()

    if action == 'checkout' and not branch_name:
        return jsonify({'error': 'Branch name is required'}), 400
    if action not in {'status', 'checkout', 'pull'}:
        return jsonify({'error': 'Invalid git action'}), 400

    def worker(log):
        if action == 'status':
            branch = run_git_status(project_path, log)
            return {'action': 'status', 'branch': branch}
        if action == 'checkout':
            output = run_git_checkout(project_path, branch_name, log)
            return {'action': 'checkout', 'branch': branch_name, 'output': output}
        output = run_git_pull(project_path, log)
        return {'action': 'pull', 'output': output}

    return _queue_event_stream(worker)


@app.route('/api/projects/<int:project_id>/git-status', methods=['GET'])
def git_status(project_id):
    projects = load_projects()
    
    if project_id < 0 or project_id >= len(projects):
        return jsonify({'error': 'Project not found'}), 404
    
    project_path = projects[project_id]['path']
    
    if not os.path.exists(project_path):
        return jsonify({'error': 'Project path does not exist'}), 404
    
    try:
        result = subprocess.run(
            ['git', 'branch', '--show-current'],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=CREATE_NO_WINDOW
        )
        current_branch = result.stdout.strip() if result.returncode == 0 else 'Not a git repository'
        
        status_result = subprocess.run(
            ['git', 'status'],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=CREATE_NO_WINDOW
        )
        status_output = status_result.stdout if status_result.returncode == 0 else 'Not a git repository'
        
        return jsonify({
            'branch': current_branch,
            'status': status_output
        })
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Git command timed out'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/projects/<int:project_id>/checkout', methods=['POST'])
def git_checkout(project_id):
    projects = load_projects()
    
    if project_id < 0 or project_id >= len(projects):
        return jsonify({'error': 'Project not found'}), 404
    
    data = request.json
    branch_name = data.get('branch', '').strip()
    
    if not branch_name:
        return jsonify({'error': 'Branch name is required'}), 400
    
    project_path = projects[project_id]['path']
    
    if not os.path.exists(project_path):
        return jsonify({'error': 'Project path does not exist'}), 404
    
    try:
        result = subprocess.run(
            ['git', 'checkout', branch_name],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=CREATE_NO_WINDOW
        )
        
        if result.returncode != 0:
            return jsonify({
                'error': 'Failed to checkout branch',
                'message': result.stderr
            }), 400
        
        return jsonify({
            'message': f'Switched to branch: {branch_name}',
            'output': result.stdout
        })
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Git command timed out'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/projects/<int:project_id>/pull', methods=['POST'])
def git_pull(project_id):
    projects = load_projects()
    
    if project_id < 0 or project_id >= len(projects):
        return jsonify({'error': 'Project not found'}), 404
    
    project_path = projects[project_id]['path']
    
    if not os.path.exists(project_path):
        return jsonify({'error': 'Project path does not exist'}), 404
    
    try:
        result = subprocess.run(
            ['git', 'pull'],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=60,
            creationflags=CREATE_NO_WINDOW
        )
        
        if result.returncode != 0:
            return jsonify({
                'error': 'Failed to pull changes',
                'message': result.stderr
            }), 400
        
        return jsonify({
            'message': 'Successfully pulled changes',
            'output': result.stdout
        })
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Git command timed out'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/projects/<int:project_id>/git-remote', methods=['GET'])
def get_git_remote(project_id):
    projects = load_projects()
    
    if project_id < 0 or project_id >= len(projects):
        return jsonify({'error': 'Project not found'}), 404
    
    project_path = projects[project_id]['path']
    
    if not os.path.exists(project_path):
        return jsonify({'error': 'Project path does not exist'}), 404
    
    try:
        result = subprocess.run(
            ['git', 'remote', 'get-url', 'origin'],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=CREATE_NO_WINDOW
        )
        
        if result.returncode != 0:
            result = subprocess.run(
                ['git', 'remote', '-v'],
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=CREATE_NO_WINDOW
            )
            if result.returncode == 0 and result.stdout:
                lines = result.stdout.strip().split('\n')
                if lines:
                    parts = lines[0].split()
                    if len(parts) >= 2:
                        remote_url = parts[1]
                    else:
                        return jsonify({'error': 'No git remote found'}), 404
                else:
                    return jsonify({'error': 'No git remote found'}), 404
            else:
                return jsonify({'error': 'Not a git repository or no remote configured'}), 404
        else:
            remote_url = result.stdout.strip()
        
        if remote_url.startswith('git@'):
            remote_url = remote_url.replace('git@', 'https://').replace(':', '/')
            if remote_url.endswith('.git'):
                remote_url = remote_url[:-4]
        elif remote_url.startswith('http'):
            if remote_url.endswith('.git'):
                remote_url = remote_url[:-4]
        else:
            return jsonify({'error': 'Unknown remote URL format'}), 400
        
        return jsonify({
            'remote_url': remote_url,
            'original_url': result.stdout.strip() if 'result' in locals() else remote_url
        })
        
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Git command timed out'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def _ps_single_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def _resolve_launch_vars(value, workspace_folder):
    if not isinstance(value, str):
        return value
    return value.replace('${workspaceFolder}', workspace_folder).replace(
        '${workspaceFolderBasename}', os.path.basename(workspace_folder)
    )


def _load_launch_config(project_path):
    launch_path = os.path.join(project_path, '.vscode', 'launch.json')
    if not os.path.exists(launch_path):
        return None, 'No .vscode/launch.json found in this project'

    try:
        with open(launch_path, 'r', encoding='utf-8') as f:
            raw = f.read()
        # Strip // comments sometimes present in VS Code JSON
        lines = []
        for line in raw.splitlines():
            stripped = line.lstrip()
            if stripped.startswith('//'):
                continue
            lines.append(line)
        data = json.loads('\n'.join(lines))
    except Exception as e:
        return None, f'Failed to read launch.json: {e}'

    configs = data.get('configurations') if isinstance(data, dict) else None
    if not isinstance(configs, list) or not configs:
        return None, 'launch.json has no configurations'

    config = configs[0]
    for candidate in configs:
        name = str(candidate.get('name', '')).lower()
        if 'odoo' in name:
            config = candidate
            break

    python_exe = _resolve_launch_vars(config.get('python') or config.get('pythonPath') or '', project_path)
    program = _resolve_launch_vars(config.get('program') or '', project_path)
    args = config.get('args') or []
    if not isinstance(args, list):
        return None, 'launch.json args must be a list'

    args = [_resolve_launch_vars(arg, project_path) for arg in args]

    if not python_exe:
        return None, 'launch.json is missing python path'
    if not program:
        return None, 'launch.json is missing program path'
    if not os.path.exists(python_exe):
        return None, f'Python not found: {python_exe}'
    if not os.path.exists(program):
        return None, f'Program not found: {program}'

    return {
        'name': config.get('name', 'Launch'),
        'python': python_exe,
        'program': program,
        'args': args,
        'cwd': project_path,
    }, None


def _open_powershell_command(project_path, command=None):
    path_escaped = project_path.replace("'", "''")
    if command:
        full_command = "Set-Location -LiteralPath '%s'; %s" % (path_escaped, command)
    else:
        full_command = "Set-Location -LiteralPath '%s'" % path_escaped
    cmd = [None, '-NoExit', '-Command', full_command]
    for exe in ('pwsh', 'pwsh.exe', 'powershell', 'powershell.exe'):
        try:
            cmd[0] = exe
            subprocess.Popen(cmd, creationflags=CREATE_NEW_CONSOLE)
            return None
        except FileNotFoundError:
            continue
    return 'PowerShell not found (tried pwsh, powershell)'


@app.route('/api/projects/<int:project_id>/open-terminal', methods=['POST'])
def open_terminal(project_id):
    projects = load_projects()
    if project_id < 0 or project_id >= len(projects):
        return jsonify({'error': 'Project not found'}), 404
    project_path = projects[project_id]['path']
    if not os.path.exists(project_path):
        return jsonify({'error': 'Project path does not exist'}), 404
    try:
        if platform.system() == 'Windows':
            err = _open_powershell_command(project_path)
            if err:
                return jsonify({'error': err}), 400
        else:
            if platform.system() == 'Darwin':
                script = 'tell application "Terminal" to do script "cd \'%s\' && exec $SHELL"' % project_path.replace("'", "'\\''")
                subprocess.Popen(['osascript', '-e', script])
            else:
                for term in ['gnome-terminal', 'xterm', 'konsole']:
                    try:
                        subprocess.Popen([term, '--working-directory', project_path])
                        break
                    except FileNotFoundError:
                        continue
                else:
                    return jsonify({'error': 'No terminal found (tried gnome-terminal, xterm, konsole)'}), 400
        return jsonify({'message': 'Terminal opened', 'path': project_path}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/projects/<int:project_id>/start', methods=['POST'])
def start_project(project_id):
    projects = load_projects()
    if project_id < 0 or project_id >= len(projects):
        return jsonify({'error': 'Project not found'}), 404

    project_path = projects[project_id]['path']
    if not os.path.exists(project_path):
        return jsonify({'error': 'Project path does not exist'}), 404

    launch, error = _load_launch_config(project_path)
    if error:
        return jsonify({'error': error}), 400

    try:
        if platform.system() == 'Windows':
            parts = [
                '&',
                _ps_single_quote(launch['python']),
                _ps_single_quote(launch['program']),
            ]
            parts.extend(_ps_single_quote(arg) for arg in launch['args'])
            run_cmd = ' '.join(parts)
            err = _open_powershell_command(project_path, run_cmd)
            if err:
                return jsonify({'error': err}), 400
        else:
            cmd = [launch['python'], launch['program']] + launch['args']
            if platform.system() == 'Darwin':
                quoted = ' '.join("'%s'" % c.replace("'", "'\\''") for c in cmd)
                script = 'tell application "Terminal" to do script "cd \'%s\' && %s"' % (
                    project_path.replace("'", "'\\''"),
                    quoted,
                )
                subprocess.Popen(['osascript', '-e', script])
            else:
                for term in ['gnome-terminal', 'xterm', 'konsole']:
                    try:
                        if term == 'gnome-terminal':
                            subprocess.Popen(
                                [term, '--working-directory', project_path, '--'] + cmd
                            )
                        else:
                            subprocess.Popen(cmd, cwd=project_path)
                        break
                    except FileNotFoundError:
                        continue
                else:
                    return jsonify({'error': 'No terminal found to show logs'}), 400

        return jsonify({
            'message': f"Started {launch['name']}",
            'python': launch['python'],
            'program': launch['program'],
            'args': launch['args'],
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/projects/<int:project_id>/open-cursor', methods=['POST'])
def open_cursor(project_id):
    projects = load_projects()
    
    if project_id < 0 or project_id >= len(projects):
        return jsonify({'error': 'Project not found'}), 404
    
    project_path = projects[project_id]['path']
    
    if not os.path.exists(project_path):
        return jsonify({'error': 'Project path does not exist'}), 404
    
    try:
        import platform
        system = platform.system()
        
        if system == 'Windows':
            try:
                subprocess.Popen(
                    ['cursor', project_path],
                    cwd=project_path,
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                return jsonify({
                    'message': f'Opening Cursor at {project_path}',
                    'command': 'cursor'
                })
            except FileNotFoundError:
                try:
                    subprocess.Popen(
                        ['code', project_path],
                        cwd=project_path,
                        shell=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                    return jsonify({
                        'message': f'Opening VS Code at {project_path} (Cursor not found)',
                        'command': 'code'
                    })
                except FileNotFoundError:
                    return jsonify({
                        'error': 'Could not find Cursor or VS Code. Make sure Cursor is installed and added to PATH.'
                    }), 400
            except Exception as e:
                return jsonify({'error': f'Error opening Cursor: {str(e)}'}), 500
        elif system == 'Darwin':
            commands = [
                ['cursor', project_path],
                ['open', '-a', 'Cursor', project_path],
            ]
        else:
            commands = [
                ['cursor', project_path],
                ['code', project_path],
            ]
        
        last_error = None
        for cmd in commands:
            try:
                result = subprocess.run(
                    cmd,
                    cwd=project_path,
                    capture_output=True,
                    text=True,
                    timeout=5,
                    shell=False,
                    creationflags=CREATE_NO_WINDOW
                )
                return jsonify({
                    'message': f'Opening Cursor at {project_path}',
                    'command': ' '.join(cmd)
                })
            except FileNotFoundError:
                last_error = f'Command not found: {cmd[0]}'
                continue
            except subprocess.TimeoutExpired:
                return jsonify({
                    'message': f'Opening Cursor at {project_path}',
                    'command': ' '.join(cmd)
                })
            except Exception as e:
                last_error = str(e)
                continue
        
        return jsonify({
            'error': f'Could not open Cursor. Make sure Cursor is installed and in your PATH. Last error: {last_error}'
        }), 400
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/open-odoo-config', methods=['POST'])
def open_odoo_config():
    settings = load_settings()
    odoo17_config_path = settings.get('odoo17_config_path')

    if not odoo17_config_path:
        return jsonify({'error': 'Odoo config path not set'}), 400
    
    if not os.path.exists(odoo17_config_path):
        return jsonify({'error': 'Odoo config file not found at the specified path'}), 404
    
    try:
        import platform
        system = platform.system()
        
        if system == 'Windows':
            try:
                subprocess.Popen(
                    ['cursor', odoo17_config_path],
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                return jsonify({
                    'message': f'Opening Odoo config in Cursor: {odoo17_config_path}',
                    'command': 'cursor'
                })
            except FileNotFoundError:
                try:
                    subprocess.Popen(
                        ['code', odoo17_config_path],
                        shell=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                    return jsonify({
                        'message': f'Opening Odoo config in VS Code: {odoo17_config_path}',
                        'command': 'code'
                    })
                except FileNotFoundError:
                    return jsonify({
                        'error': 'Could not find Cursor or VS Code. Make sure Cursor is installed and added to PATH.'
                    }), 400
            except Exception as e:
                return jsonify({'error': f'Error opening file: {str(e)}'}), 500
        else:
            try:
                subprocess.Popen(
                    ['cursor', odoo17_config_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                return jsonify({
                    'message': f'Opening Odoo config in Cursor: {odoo17_config_path}',
                    'command': 'cursor'
                })
            except FileNotFoundError:
                return jsonify({
                    'error': 'Could not find Cursor. Make sure Cursor is installed and added to PATH.'
                }), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/open-odoo-config-11', methods=['POST'])
def open_odoo_config_11():
    settings = load_settings()
    odoo11_config_path = settings.get('odoo11_config_path')

    if not odoo11_config_path:
        return jsonify({'error': 'Odoo 11 config path not set'}), 400

    odoo11_config_path = os.path.normpath(odoo11_config_path)

    if not os.path.exists(odoo11_config_path):
        return jsonify({'error': 'Odoo 11 config file not found at the specified path'}), 404

    try:
        system = platform.system()

        if system == 'Windows':
            try:
                subprocess.Popen(
                    ['cursor', odoo11_config_path],
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                return jsonify({
                    'message': f'Opening Odoo 11 config in Cursor: {odoo11_config_path}',
                    'command': 'cursor'
                })
            except FileNotFoundError:
                try:
                    subprocess.Popen(
                        ['code', odoo11_config_path],
                        shell=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                    return jsonify({
                        'message': f'Opening Odoo 11 config in VS Code: {odoo11_config_path}',
                        'command': 'code'
                    })
                except FileNotFoundError:
                    return jsonify({
                        'error': 'Could not find Cursor or VS Code. Make sure Cursor is installed and added to PATH.'
                    }), 400
            except Exception as e:
                return jsonify({'error': f'Error opening file: {str(e)}'}), 500
        else:
            try:
                subprocess.Popen(
                    ['cursor', odoo11_config_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                return jsonify({
                    'message': f'Opening Odoo 11 config in Cursor: {odoo11_config_path}',
                    'command': 'cursor'
                })
            except FileNotFoundError:
                return jsonify({
                    'error': 'Could not find Cursor. Make sure Cursor is installed and added to PATH.'
                }), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/settings/odoo-config-path', methods=['GET'])
def get_odoo17_config_path():
    settings = load_settings()
    return jsonify({'odoo17_config_path': settings.get('odoo17_config_path')}), 200

@app.route('/api/settings/odoo-config-path', methods=['POST'])
def set_odoo17_config_path():
    data = request.json or {}
    path = data.get('odoo17_config_path', '').strip()

    if not path:
        return jsonify({'error': 'odoo17_config_path is required'}), 400

    path = os.path.normpath(path)

    if not os.path.exists(path):
        return jsonify({'error': 'Odoo config file not found at the specified path'}), 404

    settings = load_settings()
    settings['odoo17_config_path'] = path
    save_settings(settings)

    return jsonify({'message': 'Odoo config path saved', 'odoo17_config_path': path}), 200

@app.route('/api/settings/odoo11-config-path', methods=['GET'])
def get_odoo11_config_path():
    settings = load_settings()
    return jsonify({'odoo17_config_path': settings.get('odoo11_config_path')}), 200

@app.route('/api/settings/odoo11-config-path', methods=['POST'])
def set_odoo11_config_path():
    data = request.json or {}
    path = data.get('odoo17_config_path', '').strip()

    if not path:
        return jsonify({'error': 'odoo17_config_path is required'}), 400

    path = os.path.normpath(path)

    if not os.path.exists(path):
        return jsonify({'error': 'Odoo config file not found at the specified path'}), 404

    settings = load_settings()
    settings['odoo11_config_path'] = path
    save_settings(settings)

    return jsonify({'message': 'Odoo 11 config path saved', 'odoo17_config_path': path}), 200

@app.route('/api/docker-restore/detect', methods=['POST'])
def docker_restore_detect():
    data = request.json or {}
    backup_path = data.get('backup_path', '').strip()
    if not backup_path:
        return jsonify({'error': 'backup_path is required'}), 400

    try:
        info = detect_backup_info(backup_path)
        return jsonify({
            'backup_path': info['backup_path'],
            'db_name': info['db_name'],
            'container_name': info['container_name'],
            'port': info['port'],
            'has_filestore': info['has_filestore'],
        }), 200
    except Exception as exc:
        return jsonify({'error': str(exc)}), 400


@app.route('/api/docker-restore/restore', methods=['POST'])
def docker_restore_run():
    data = request.json or {}
    backup_path = data.get('backup_path', '').strip()
    db_name = data.get('db_name', '').strip() or None
    odoo_sessions_dir = data.get('odoo_sessions_dir', '').strip() or None

    if not backup_path:
        return jsonify({'error': 'backup_path is required'}), 400

    settings = load_settings()
    if not odoo_sessions_dir:
        odoo_sessions_dir = settings.get('odoo_sessions_dir', r'C:\Users\i.tila\Documents\Odoo17\sessions')

    try:
        result = restore_docker_database(
            backup_path=backup_path,
            db_name=db_name,
            odoo_sessions_dir=odoo_sessions_dir,
        )

        instances = settings.get('docker_db_instances', {})
        instances[result['db_name']] = {
            'backup_path': os.path.normpath(backup_path),
            'container_name': result['container_name'],
            'port': result['port'],
        }
        settings['docker_db_instances'] = instances
        settings['odoo_sessions_dir'] = odoo_sessions_dir
        save_settings(settings)

        return jsonify(result), 200
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


def _save_restore_settings(settings, backup_path, result, odoo_sessions_dir):
    instances = settings.get('docker_db_instances', {})
    instances[result['db_name']] = {
        'backup_path': os.path.normpath(backup_path),
        'container_name': result['container_name'],
        'port': result['port'],
    }
    settings['docker_db_instances'] = instances
    settings['odoo_sessions_dir'] = odoo_sessions_dir
    save_settings(settings)


@app.route('/api/docker-restore/restore-stream', methods=['POST'])
def docker_restore_stream():
    data = request.json or {}
    backup_path = data.get('backup_path', '').strip()
    db_name = data.get('db_name', '').strip() or None
    odoo_sessions_dir = data.get('odoo_sessions_dir', '').strip() or None

    if not backup_path:
        return jsonify({'error': 'backup_path is required'}), 400

    settings = load_settings()
    if not odoo_sessions_dir:
        odoo_sessions_dir = settings.get('odoo_sessions_dir', r'C:\Users\i.tila\Documents\Odoo17\sessions')

    def event_stream():
        log_queue = queue.Queue()

        def worker():
            try:
                result = restore_docker_database(
                    backup_path=backup_path,
                    db_name=db_name,
                    odoo_sessions_dir=odoo_sessions_dir,
                    log_callback=lambda message: log_queue.put(('log', message)),
                )
                _save_restore_settings(settings, backup_path, result, odoo_sessions_dir)
                log_queue.put(('done', result))
            except Exception as exc:
                log_queue.put(('error', str(exc)))

        threading.Thread(target=worker, daemon=True).start()

        while True:
            kind, payload = log_queue.get()
            if kind == 'log':
                yield f"data: {json.dumps({'type': 'log', 'message': payload})}\n\n"
            elif kind == 'done':
                yield f"data: {json.dumps({'type': 'done', 'result': payload})}\n\n"
                break
            elif kind == 'error':
                yield f"data: {json.dumps({'type': 'error', 'message': payload})}\n\n"
                break

    return _sse_response(event_stream)


@app.route('/api/path/resolve', methods=['POST'])
def resolve_path():
    data = request.json
    folder_name = data.get('folder_name', '').strip()
    search_paths = data.get('search_paths', [])
    
    if not folder_name:
        return jsonify({'error': 'Folder name is required'}), 400
    
    found_paths = []
    
    if not search_paths:
        user_home = os.path.expanduser('~')
        search_paths = [
            user_home,
            os.path.join(user_home, 'Desktop'),
            os.path.join(user_home, 'Documents'),
            os.path.join(user_home, 'Downloads'),
            'C:\\',
            'D:\\',
        ]
    
    def search_directory(dir_path, max_depth=2, current_depth=0):
        if current_depth >= max_depth or len(found_paths) >= 10:
            return
        
        try:
            if not os.path.exists(dir_path) or not os.path.isdir(dir_path):
                return
            
            target_path = os.path.join(dir_path, folder_name)
            if os.path.exists(target_path) and os.path.isdir(target_path):
                found_paths.append(target_path)
                if len(found_paths) >= 10:
                    return
            
            if current_depth < max_depth - 1:
                try:
                    items = os.listdir(dir_path)
                    for item in items:
                        if len(found_paths) >= 10:
                            break
                        item_path = os.path.join(dir_path, item)
                        try:
                            if os.path.isdir(item_path) and not item.startswith('.'):
                                search_directory(item_path, max_depth, current_depth + 1)
                        except (PermissionError, OSError):
                            continue
                except (PermissionError, OSError):
                    pass
        except (PermissionError, OSError):
            pass
    
    for search_path in search_paths:
        if os.path.exists(search_path):
            search_directory(search_path, max_depth=2)
            if len(found_paths) >= 10:
                break
    
    return jsonify({
        'folder_name': folder_name,
        'found_paths': found_paths[:10]
    })

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
