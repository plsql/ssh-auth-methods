import subprocess, sys, threading
from queue import Queue
from math import ceil
from time import sleep

def get_auth_methods(hostname, port=22, timeout=5.0, verbose=False):
    try:
        if sys.version_info.minor < 3:
            success_output = subprocess.check_output([
                'ssh',
                # prevents ominous error on changed host key
                '-o', 'StrictHostKeyChecking=no',
                # the point - prevents attempted authentication
                '-o', 'PreferredAuthentications=none',
                # prevents warning associated with unrecognized host key
                '-o', 'LogLevel=ERROR',
                # maximum time per connections
                # NOTE: there can be multiple connections if a domain
                # resolves to multiple IPs
                '-o', 'ConnectTimeout=%d' % ceil(timeout),
                '-p', str(port),
                'root@' + hostname,    # use root user to prevent leaking username
                'exit'],    # the command to be executed upon successful auth
                stderr=subprocess.STDOUT)
        else:
            success_output = subprocess.check_output([
                'ssh',
                '-o', 'StrictHostKeyChecking=no',
                '-o', 'PreferredAuthentications=none',
                '-o', 'LogLevel=ERROR',
                '-p', str(port),
                'root@' + hostname,
                'exit'],
                stderr=subprocess.STDOUT,
                # only available in Python 3.3+ (reason for condition_
                timeout=timeout)
        # If we make it here, the server allowed us shell access without
        # authentication. Thankfully, the 'exit' command should have
        # left immediately.
        if verbose:
            print('Eek! Server allowed unauthenticated login! Exiting.')
        return ['none']
    # This is in fact the expected case, as we expect the SSH server to
    # reject the unauthenticated connection, and therefore expect exit code
    # 255, OpenSSH's sole error code.
    except subprocess.CalledProcessError as e:
        # ssh's result to stderr
        result = str(e.output.strip(), 'utf-8')

        if e.returncode != 255:
            if verbose:
                print('Eek! Server allowed unauthenticated login! '
                'Also, the command passed had a non-zero exit status.')
            return ['none']

        elif result.startswith('ssh: Could not resolve hostname'):
            if verbose:
                print('hostname resolution failed - '
                'maybe the server is down, '
                'the SSH server is on another port, '
                'or your IP is blacklisted?')
            raise Exception('resolution of hostname ' +  hostname + ' failed')

        elif result.endswith('Connection timed out'):
            raise Exception('connection to ' + hostname + ' timed out')

        elif result.startswith('Permission denied (') \
                and result.endswith(').'):
            # assume the format specified in the above condition with
            # comma-delimited auth methods
            return result[19:-2].split(',')

        else:
            raise Exception('unexpected SSH error response: ' + result)
    # we leave subprocess.TimeoutExpired uncaught, so it will propagate


def _ssh_worker(host_queue, response_queue, ssh_args):
    
    hostname = host_queue.get()

    try:
        resp = get_auth_methods(hostname, **ssh_args)
    except:
        resp = None

    response_queue.put((hostname, resp))
    host_queue.task_done()


def threaded_auth_methods(response_queue, host_file=sys.stdin, delay=0.1, timeout=5.0, verbose=False):
    # All get_auth_methods() args aside from hostname are optional,
    # and are the same across all calls.
    # We therefore use a dict of args that is unpacked in calls.
    # TODO: add port
    ssh_args = {'verbose': verbose, 'timeout': timeout}
    host_queue = Queue()

    num_hosts = 0

    for line in host_file:
        num_hosts += 1
        host_queue.put(line.strip())
        t = threading.Thread(
                target=_ssh_worker,
                args=[host_queue, response_queue, ssh_args])
        t.start()
        sleep(delay)

    host_queue.join()


def _print_response_thread(response_queue, outfile=sys.stdout):
    while True:
        hostname, methods = response_queue.get()
        if methods is None:
            print(hostname, file=outfile)
        else:
            print('\t'.join([hostname] + methods),
                    file=outfile)
        response_queue.task_done()


def main():
    if sys.version_info.major != 3:
        print('this script only runs on Python 3, which should be '
                'available on your platform',
                file=sys.stderr)
        sys.exit(1)
    # the only two currently acceptable argument situations
    # a more complex argument system (using argparse, for example) may
    # be added later if needed.
    if len(sys.argv) == 1 or \
            len(sys.argv) == 2 and sys.argv[1] == '--verbose':
        verbose = len(sys.argv) == 2

        response_queue = Queue()

        master_thread = threading.Thread(
                target=threaded_auth_methods,
                kwargs={'response_queue': response_queue, 'verbose': verbose})
        master_thread.daemon = True
        master_thread.start()

        print_thread = threading.Thread(
                target=_print_response_thread,
                args=(response_queue,))
        print_thread.daemon = True
        print_thread.start()

        master_thread.join()
        response_queue.join()


    else:
        print('ERROR: input must be line-delimited hostnames from stdin',
                file=sys.stdin)
        print('usage: python3 ssh_password.py [-v]',
                file=sys.stdin)
        sys.exit(1)


if __name__ == '__main__':
    main()
