"""Example of a custom scene: orbital assembly around any nominated surface or imported model."""
import math
import random


def build_scene(ctx):
    cube=ctx['cube']
    material=ctx['material']
    pose=ctx['pose']
    duration=ctx['duration']
    rng=random.Random(ctx['plan']['effect'].get('seed',4117))
    gold=material('Orbital copper',(.94,.56,.19),.72,.23)
    silver=material('Orbital ceramic',(.78,.91,.94),.45,.19)
    azure=material('Orbital blue',(.13,.57,.83),.35,.25,.3)
    if ctx['plan'].get('assets',{}).get('hero'):
        ctx['import_model']('hero')
    for index in range(40):
        angle=math.tau*index/40
        radius=.34 if index%2 else .46
        elevation=.06 if index%2 else .18
        scale=.026+rng.random()*.025
        obj=cube(f'Orbiting element {index:02}',(0,0,0),(scale,scale,scale),[gold,silver,azure][index%3],.004)
        pose(obj,0,scale=.001)
        for step in range(17):
            t=step/16
            a=angle+t*math.tau*.85
            radius_now=radius*(.58+.42*math.sin(math.pi*t))
            xyz=(math.cos(a)*radius_now,math.sin(a)*radius_now*.60,elevation+.10*math.sin(a*2))
            amount=min(1,t/.17,(1-t)/.17)
            pose(obj,t*(duration-.04),location=xyz,rotation=(a*.7,a*.33,a),scale=max(.001,amount))
    # The rig, measured camera, lighting, alpha render and music are supplied by the common engine.
