#!/usr/bin/env node
/** Local deterministic web artwork capture. Not a logged-in browser publisher. */
import {createRequire} from 'node:module';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {pathToFileURL} from 'node:url';
import {execFileSync} from 'node:child_process';
const help = `Usage: node capture_web.mjs --input page.html --output new-folder [options]
  --mode still|slices|video|gif  default still
  --width 1080 --height 1440   viewport (video requires even dimensions)
  --slice-height 1600         vertical slice height
  --time 0                   deterministic still time, seconds
  --seconds 6 --fps 24        animation duration and frame rate
  --browser /path/to/chromium optional installed browser executable
Requires: npm install playwright; npx playwright install chromium
Animation pages must implement window.renderFrame(seconds).
Network requests are blocked; use local files. Video/GIF additionally require ffmpeg.
Output is always local and has no account/publishing side effects.`;
const args = process.argv.slice(2);
if (args.includes('--help') || !args.length) {console.log(help);process.exit(0);}
const opts = {};
const allowed = new Set(['input','output','mode','width','height','slice-height','time','seconds','fps','browser']);
for(let i=0;i<args.length;i+=2){
  const key=args[i].replace(/^--/,'');
  if(!args[i].startsWith('--') || !allowed.has(key) || args[i+1]===undefined) throw Error(`Invalid option ${args[i]}`);
  opts[key]=args[i+1];
}
function number(key,fallback,min,max){const v=Number(opts[key]??fallback);if(!Number.isFinite(v)||v<min||v>max)throw Error(`Invalid ${key}`);return v;}
const mode=opts.mode??'still', width=number('width',1080,160,4096), height=number('height',1440,160,4096);
const time=number('time',0,0,86400),seconds=number('seconds',6,.1,300),fps=number('fps',24,1,60),sliceHeight=number('slice-height',1600,160,8192);
if(!['still','slices','video','gif'].includes(mode))throw Error('Invalid mode');
if(!Number.isInteger(width)||!Number.isInteger(height)||!Number.isInteger(sliceHeight))throw Error('Viewport dimensions must be integers');
if(!opts.input||!opts.output)throw Error('input and output required');
const input=path.resolve(opts.input), output=path.resolve(opts.output);
if((mode==='video'||mode==='gif')&&(width%2||height%2))throw Error('Video dimensions must be even');
await fs.access(input);
try{const old=await fs.readdir(output);if(old.length)throw Error('Output is not empty; use a new revision folder');}catch(e){if(e.code!=='ENOENT')throw e;}
let chromium;
try{({chromium}=createRequire(import.meta.url)('playwright'));}catch{throw Error('Install optional dependency: npm install playwright, then npx playwright install chromium');}
if(mode==='video'||mode==='gif')execFileSync('ffmpeg',['-version'],{stdio:'ignore'});
await fs.mkdir(output,{recursive:true});
let browser,temp;
try{
  browser=await chromium.launch({headless:true,...(opts.browser?{executablePath:opts.browser}:{})});
  const page=await browser.newPage({viewport:{width,height},deviceScaleFactor:1,reducedMotion:'reduce'});
  await page.route('**/*',route=>{
    const protocol=new URL(route.request().url()).protocol;
    return ['file:','data:','blob:'].includes(protocol)?route.continue():route.abort();
  });
  const runtimeErrors=[];page.on('pageerror',e=>runtimeErrors.push(e.message));
  await page.goto(pathToFileURL(input).href,{waitUntil:'load'});
  await page.evaluate(async()=>{await document.fonts.ready;await Promise.all([...document.images].map(im=>im.decode()));});
  const hasRenderer=await page.evaluate(()=>typeof window.renderFrame==='function');
  const seek=async t=>{if(hasRenderer)await page.evaluate(async t=>{await window.renderFrame(t);},t);};
  await seek(time);
  const files=[];
  if(mode==='still'){
    const file='still.png';await page.screenshot({path:path.join(output,file),fullPage:true});files.push(file);
  }else if(mode==='slices'){
    const docHeight=await page.evaluate(()=>Math.max(document.documentElement.scrollHeight,document.body.scrollHeight));
    for(let y=0,n=1;y<docHeight;y+=sliceHeight,n++){
      const file=`slice-${String(n).padStart(2,'0')}.png`;
      await page.screenshot({path:path.join(output,file),clip:{x:0,y,width,height:Math.min(sliceHeight,docHeight-y)},captureBeyondViewport:true});files.push(file);
    }
    const tags=files.map(f=>`<img src="${f}" style="display:block;width:100%;height:auto;margin:0" alt="Story slice">`).join('');
    await fs.writeFile(path.join(output,'preview.html'),`<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width"><main style="max-width:${width}px;margin:auto">${tags}</main>`);
  }else{
    if(!hasRenderer)throw Error('Animation export requires window.renderFrame(seconds); wall-clock recording is not deterministic.');
    temp=await fs.mkdtemp(path.join(os.tmpdir(),'storytelling-frames-'));
    const count=Math.ceil(seconds*fps);
    for(let i=0;i<count;i++){
      await seek(time+i/fps);
      await page.screenshot({path:path.join(temp,`frame-${String(i).padStart(6,'0')}.png`)});
    }
    if(runtimeErrors.length)throw Error(runtimeErrors.join('\n'));
    const mp4=mode==='video'?path.join(output,'motion.mp4'):path.join(temp,'motion.mp4');
    execFileSync('ffmpeg',['-v','error','-y','-framerate',String(fps),'-i',path.join(temp,'frame-%06d.png'),'-an','-c:v','libx264','-pix_fmt','yuv420p','-crf','18','-movflags','+faststart',mp4]);
    if(mode==='gif'){
      execFileSync('ffmpeg',['-v','error','-y','-i',mp4,'-filter_complex','[0:v]split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=3','-loop','0',path.join(output,'motion.gif')]);files.push('motion.gif');
    }else files.push('motion.mp4');
  }
  if(runtimeErrors.length)throw Error(runtimeErrors.join('\n'));
  await fs.writeFile(path.join(output,'capture.json'),JSON.stringify({mode,width,height,startTime:time,...(['video','gif'].includes(mode)?{fps,frames:Math.ceil(seconds*fps),duration:Math.ceil(seconds*fps)/fps}:{}),files,audio:false,publication_state:'local_only'},null,2));
  console.log(JSON.stringify({output,files}));
}finally{
  if(browser)await browser.close();
  if(temp)await fs.rm(temp,{recursive:true,force:true});
}
