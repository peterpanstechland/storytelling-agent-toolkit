"""Extract visible scene evidence for the Agent before it designs any CG."""
import json
from pathlib import Path
import subprocess

from PIL import Image,ImageDraw


def inspect(source,out,ffmpeg,ffprobe,start=0,duration=8):
    if out.exists() and any(out.iterdir()):raise ValueError('Choose a new scene-inspection output directory.')
    source=source.resolve()
    probe=json.loads(subprocess.check_output([str(ffprobe),'-v','error','-show_streams','-show_format','-of','json',str(source)]))
    video=next(s for s in probe['streams'] if s['codec_type']=='video')
    still=source.suffix.lower() in ('.png','.jpg','.jpeg','.webp','.tif','.tiff')
    available=duration if still else float(probe['format']['duration'])-start
    length=min(duration,available)
    if length<=0:raise ValueError('Inspection range is outside the source.')
    out.mkdir(parents=True,exist_ok=True)
    count=1 if still else 6
    times=[start+i*length*.96/max(count-1,1) for i in range(count)]
    frames=[]
    for n,t in enumerate(times):
        file=out/f'frame-{n:02d}.jpg'
        inputs=[] if still else ['-ss',str(t)]
        subprocess.run([str(ffmpeg),'-v','error','-nostdin','-y',*inputs,'-i',str(source),'-frames:v','1',
                        '-vf','scale=960:-2:flags=lanczos',str(file)],check=True)
        frames.append(Image.open(file).convert('RGB'))
    w,h=frames[0].size
    canvas=Image.new('RGB',(w*2,(h+34)*((count+1)//2)),(19,22,24))
    draw=ImageDraw.Draw(canvas)
    for n,frame in enumerate(frames):
        x=(n%2)*w;y=(n//2)*(h+34)
        canvas.paste(frame,(x,y));draw.text((x+12,y+h+10),f'Frame {n}: source {times[n]:.3f}s',fill=(235,239,231))
    canvas.save(out/'contact.jpg',quality=92)
    record=dict(source=str(source),start=start,duration=length,contact=str(out/'contact.jpg'),
                frames=[dict(file=str(out/f'frame-{n:02d}.jpg'),source_time=t) for n,t in enumerate(times)],
                source_video=video,color='Source preview only; technical color normalization must be established before CG rendering.',
                next='Agent must view the images, identify objects and motion, then choose scene reconstruction, tracking and interaction.')
    (out/'inspection.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print(str(out/'contact.jpg'),flush=True)
