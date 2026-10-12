import os, shutil, subprocess, sys, tempfile, time
n_fail = 0
def run(args, cwd, env):
    return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True)
def one(i):
    d = tempfile.mkdtemp()
    env = dict(os.environ, HOME=d, GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0")
    for k in ("GIT_AUTHOR_NAME","GIT_AUTHOR_EMAIL","GIT_COMMITTER_NAME","GIT_COMMITTER_EMAIL"): env.pop(k, None)
    r = run(["init","-q","--bare","-b","main","origin.git"], d, env); assert r.returncode == 0, r.stderr
    r = run(["clone","-q","origin.git","dev"], d, env); assert r.returncode == 0, r.stderr
    dev = os.path.join(d, "dev")
    os.makedirs(os.path.join(dev, "data", "launch"))
    open(os.path.join(dev, "code.py"), "w").write("v1\n")
    for args in (["add","-A"],["-c","user.name=dev","-c","user.email=dev@x","commit","-qm","init"],["push","-q","origin","main"]):
        r = run(args, dev, env); assert r.returncode == 0, r.stderr
    r = run(["clone","-q","origin.git","server"], d, env)
    shutil.rmtree(d, ignore_errors=True)
    return r
fails = []
t0 = time.time()
i = 0
while time.time() - t0 < float(sys.argv[1]):
    r = one(i); i += 1
    if r.returncode != 0:
        fails.append((i, r.returncode, r.stderr[:600]))
print("runs", i, "fails", len(fails)); print(fails[:3])
