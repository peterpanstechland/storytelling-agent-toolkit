"""Isolated optional CG workers; never install packages into the voice environment."""
import json
import os
from pathlib import Path
import subprocess


def configuration():
    script=Path(__file__).resolve()
    result={}
    for parent in reversed(script.parents):
        local=parent/'.runtime/cg.runtime.json'
        if local.is_file():result.update(json.loads(local.read_text(encoding='utf-8-sig')))
    installed=script.parent.parent/'runtime.local.json'
    if installed.is_file():
        local=json.loads(installed.read_text(encoding='utf-8-sig'))
        result.update(local.get('scene_runtime',{}))
    return result


def worker(action,folder,*,log=None):
    runtime=configuration()
    python=runtime.get('gpu_python')
    if not python or not Path(python).is_file():
        raise ValueError('Configure the isolated scene runtime before using reconstruction or segmentation.')
    env=os.environ.copy()
    env['PYTHONPATH']=os.pathsep.join(runtime.get('pythonpaths',[]))
    env['HF_HUB_OFFLINE']='1'
    env['MPLCONFIGDIR']=str(Path(folder)/'matplotlib-cache')
    env['CUDA_MODULE_LOADING']='LAZY'
    config=Path(folder)/'scene-runtime.private.json'
    config.write_text(json.dumps(runtime,ensure_ascii=False,indent=2),encoding='utf-8')
    command=[python,str(Path(__file__).with_name('scene_worker.py')),action,'--job',str(folder),'--runtime',str(config)]
    if log:
        with Path(log).open('w',encoding='utf-8') as stream:
            subprocess.run(command,env=env,stdout=stream,stderr=subprocess.STDOUT,check=True)
    else:subprocess.run(command,env=env,check=True)
