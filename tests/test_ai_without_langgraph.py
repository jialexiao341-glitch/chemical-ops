import os
import subprocess
import sys


def test_agent_modules_load_without_langgraph():
    code = '''
import builtins
real_import = builtins.__import__
def blocked(name, *args, **kwargs):
    if name == "langgraph" or name.startswith("langgraph."):
        raise ImportError("langgraph intentionally unavailable")
    return real_import(name, *args, **kwargs)
builtins.__import__ = blocked
from app.modules.ai_agent.business_queries import text2sql
from app.modules.ai_agent.agent_execution import agent_runtime
'''
    env = dict(os.environ)
    env['PYTHONPATH'] = os.pathsep.join(filter(None, ['backend', env.get('PYTHONPATH')]))
    result = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
