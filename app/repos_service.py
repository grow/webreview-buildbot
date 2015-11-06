import git
import md5
import os


def get_workspace_root():
  if not os.path.isdir('/data'):
    # Handle non-docker environments. :|
    return '/tmp/grow/workspaces/'
  return '/data/grow/workspaces/'


def get_work_dir(job_id):
  workdir = get_workspace_root() + str(job_id)
  return workdir


def get_repo(job_id):
  git.Repo(get_work_dir(job_id))


def clone_repo(job_id, url, branch):
  work_dir = get_work_dir(job_id)
  if not os.path.exists(work_dir):
    repo = git.Repo.clone_from(url, work_dir, depth=50)
  else:
    repo = git.Repo(work_dir)
  try:
    repo.git.checkout(b=branch)
  except git.GitCommandError as e:
    if 'already exists' in str(e):
      repo.git.checkout(branch)
  return repo


def init_repo(job_id, url, branch):
  repo = clone_repo(job_id, url, branch)
  origin = repo.remotes.origin
  origin.fetch()
  origin.pull()
  return repo


def update(repo, branch, path, content, sha, message=None, committer=None, author=None):
  # TODO: Verify workspace file sha against one provided by user.
  origin = repo.remotes.origin
  origin.pull()
  repo.create_head(branch, origin.refs[branch]).set_tracking_branch(origin.refs[branch])
  path = os.path.join(repo.working_tree_dir, path)
  if not os.path.exists(os.path.dirname(path)):
    os.makedirs(os.path.dirname(path))
  with open(path, 'w') as f:
    f.write(content)
  repo.index.add([path])
  author = git.Actor(author['name'], author['email']) if author else None
  committer = git.Actor(committer['name'], committer['email']) if committer else None
  repo.index.commit(message, author=author, committer=committer)
  origin.push()
  repo.git.log()
  return repo.remotes.origin.url
