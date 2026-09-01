
import os
import subprocess

if os.name == 'nt':
    CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW
else:
    CREATE_NO_WINDOW = 0


def run_git_stream(project_path, git_args, log, timeout=300):
    command = ['git'] + git_args
    log(f'$ git {" ".join(git_args)}')
    proc = subprocess.Popen(
        command,
        cwd=project_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        creationflags=CREATE_NO_WINDOW,
    )
    output_lines = []
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            cleaned = line.rstrip('\n')
            if cleaned:
                log(cleaned)
                output_lines.append(cleaned)
        returncode = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        proc.kill()
        raise RuntimeError('Git command timed out') from exc

    if returncode != 0:
        message = '\n'.join(output_lines) or 'Git command failed'
        raise RuntimeError(message)

    return '\n'.join(output_lines)


def run_git_status(project_path, log):
    branch = run_git_stream(project_path, ['branch', '--show-current'], log, timeout=30)
    log('')
    run_git_stream(project_path, ['status'], log, timeout=30)
    return branch


def run_git_checkout(project_path, branch_name, log):
    return run_git_stream(project_path, ['checkout', branch_name], log, timeout=60)


def run_git_pull(project_path, log):
    return run_git_stream(project_path, ['pull'], log, timeout=300)
