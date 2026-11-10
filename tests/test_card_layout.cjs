/* Execute the staged card, including its real canvas transforms and send path.
 * Tiny synthetic pixel images and an affine canvas fake; no DOM/network/HA.
 */
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const assert=require('node:assert/strict');
const {test}=require('node:test');
const source=fs.readFileSync(path.join(__dirname,'../custom_components/switchbot_frame_control/frontend/frame-upload-card.js'),'utf8');
const multiply=(a,b)=>[a[0]*b[0]+a[2]*b[1],a[1]*b[0]+a[3]*b[1],a[0]*b[2]+a[2]*b[3],a[1]*b[2]+a[3]*b[3],a[0]*b[4]+a[2]*b[5]+a[4],a[1]*b[4]+a[3]*b[5]+a[5]];
class Canvas {
  width=0;height=0;pixels=[];
  getContext(){
    if(this.ctx)return this.ctx;
    let matrix=[1,0,0,1,0,0];const canvas=this;
    return this.ctx={
      translate(x,y){matrix=multiply(matrix,[1,0,0,1,x,y]);},
      rotate(a){matrix=multiply(matrix,[Math.cos(a),Math.sin(a),-Math.sin(a),Math.cos(a),0,0]);},
      fillRect(){canvas.pixels=Array(canvas.width*canvas.height).fill(0);},
      drawImage(image,...args){
        let sx=0,sy=0,sw=image.width,sh=image.height,dx,dy,dw,dh;
        if(args.length===2){[dx,dy]=args;dw=sw;dh=sh;}
        else if(args.length===4){[dx,dy,dw,dh]=args;}
        else [sx,sy,sw,sh,dx,dy,dw,dh]=args;
        const [a,b,c,d,e,f]=matrix,det=a*d-b*c;
        for(let y=0;y<canvas.height;y++)for(let x=0;x<canvas.width;x++){
          const xx=x+.5-e,yy=y+.5-f;
          const u=(d*xx-c*yy)/det,v=(-b*xx+a*yy)/det;
          if(u>=dx-.00001&&u<dx+dw&&v>=dy-.00001&&v<dy+dh){
            const ix=Math.min(image.width-1,Math.max(0,Math.floor(sx+(u-dx)*sw/dw)));
            const iy=Math.min(image.height-1,Math.max(0,Math.floor(sy+(v-dy)*sh/dh)));
            canvas.pixels[y*canvas.width+x]=image.pixels[iy*image.width+ix];
          }
        }
      },
    };
  }
  toDataURL(){return 'data:image/jpeg;base64,'+Buffer.from(JSON.stringify({width:this.width,height:this.height,pixels:this.pixels})).toString('base64');}
}
const document={createElement:tag=>tag==='canvas'?new Canvas():element()};
function element(){return {value:'',textContent:'',style:{},files:[],hidden:false,disabled:false,setAttribute(){},removeAttribute(){},replaceChildren(){},append(){}};}
let Card;
vm.runInNewContext(source,{HTMLElement:class{},customElements:{get(){return undefined;},define(name,cls){Card=cls;}},document,
  window:{customCards:[]},console,URL,Blob,setInterval:()=>1,clearInterval:()=>{},setTimeout,clearTimeout});
function fixture(id='example_frame'){
  const card=Object.create(Card.prototype),nodes=new Map();
  card.shadowRoot={querySelector(selector){if(!nodes.has(selector))nodes.set(selector,element());return nodes.get(selector);},querySelectorAll(){return [];}};
  card.config={};card.selectedFrame=id;card.layouts={[id]:{orientation:'portrait',flipped:false}};card.layoutRevisions={[id]:0};
  card.frames=[{id,name:id,model:id==='example_frame'?'frame1':'frame2',status_entity:'sensor.'+id,width:8,height:6}];
  card._hass={states:{['sensor.'+id]:{attributes:{connection_mode:'wifi',layout:{orientation:'portrait',flipped:false},layout_revision:0}}}};
  card.sourceURL='synthetic-original';card.generatedData='synthetic-original';
  const image={width:6,height:8,pixels:[]};
  for(let y=0;y<8;y++)for(let x=0;x<6;x++)image.pixels.push((y<4?0:2)+(x<3?1:2));
  card.decodeSource=async()=>image;
  card.restoreLayout();
  let server={orientation:'portrait',flipped:true},revision=1,uploads=[];
  card._hass.callApi=async(method,endpoint,data)=>{
    if(endpoint==='switchbot_frame_control/frames'){
      if(method==='POST'){
        if(data.expected_revision!==revision)throw Error('Saved layout changed in another session');
        server={...data.layout};revision++;return {layout:server,layout_revision:revision};
      }
      return {frames:[{...card.frames[0],layout:server,layout_revision:revision}]};
    }
    if(endpoint==='switchbot_frame_control/upload'){uploads.push(data);return {accepted:true};}
    if(endpoint==='switchbot_frame_control/generate')return {image:'generated-synthetic'};
    if(endpoint.startsWith('frame_art_gallery/image/'))return {image:'gallery-synthetic'};
    throw Error('Unexpected endpoint '+endpoint);
  };
  return {card,nodes,uploads,setServer(layout,rev){server=layout;revision=rev;}};
}
function corners(data){const {width:w,height:h,pixels:p}=data;return [p[0],p[w-1],p[(h-1)*w],p[h*w-1]];}
function uploadedPixels(upload){return JSON.parse(Buffer.from(upload.image,'base64').toString());}

test('portrait false/true applies exactly one 180-degree transform',async()=>{
  const {card}=fixture();
  const normal=await card.preparePicture();
  assert.deepEqual(corners(normal.transport),[2,4,1,3]);
  card.flipped=true;
  const corrected=await card.preparePicture();
  assert.deepEqual(corners(corrected.transport),[3,1,4,2]);
  assert.equal(corrected.transport.width,8);assert.equal(corrected.transport.height,6);
});
test('ordinary upload fetches authoritative layout immediately before send',async()=>{
  const {card,uploads}=fixture();
  await card.send();assert.equal(uploads.length,1);
  assert.equal(uploads[0].layout.flipped,true);
  assert.deepEqual(corners(uploadedPixels(uploads[0])),[3,1,4,2]);
});
test('generated image uses the same saved correction exactly once',async()=>{
  const {card,uploads}=fixture();card.shadowRoot.querySelector('textarea').value='Synthetic image';
  await card.generate();await card.send();assert.equal(uploads.length,1);
  assert.deepEqual(corners(uploadedPixels(uploads[0])),[3,1,4,2]);
});
test('gallery browser send uses the same saved correction exactly once',async()=>{
  const {card,uploads}=fixture();
  await card.chooseGallery({id:'synthetic',name:'Synthetic image'});await card.send();
  assert.equal(uploads.length,1);assert.deepEqual(corners(uploadedPixels(uploads[0])),[3,1,4,2]);
});
test('another frame keeps its own false layout; no global correction',async()=>{
  const f=fixture('ready_room');f.setServer({orientation:'portrait',flipped:false},0);
  await f.card.send();assert.deepEqual(corners(uploadedPixels(f.uploads[0])),[2,4,1,3]);
});
test('late hass snapshot cannot overwrite fresher HTTP layout',async()=>{
  const {card}=fixture();await card.syncLayout('example_frame');
  card.updateStatus();assert.equal(card.flipped,true);assert.equal(card.layoutRevisions.example_frame,1);
});
test('layout change in another browser propagates through revision',async()=>{
  const {card}=fixture();await card.syncLayout('example_frame');
  card._hass.states['sensor.example_frame'].attributes={layout:{orientation:'landscape',flipped:false},layout_revision:2};
  card.updateStatus();assert.equal(card.flipped,false);assert.equal(card.shadowRoot.querySelector('#orientation').value,'landscape');
});
test('successful queued layout save clears optimistic write and adopts revision',async()=>{
  const f=fixture();f.setServer({orientation:'portrait',flipped:false},0);const {card}=f;
  card.flipped=true;card.rememberLayout();await card.pendingLayoutSave;
  assert.equal(card.layoutWrites.example_frame,undefined);assert.equal(card.layoutRevisions.example_frame,1);
  card.updateStatus();assert.equal(card.flipped,true);
});
test('rapid queued toggles use the previous save revision without overwriting latest intent',async()=>{
  const f=fixture();f.setServer({orientation:'portrait',flipped:false},0);const {card}=f;
  card.flipped=true;card.rememberLayout();card.flipped=false;card.rememberLayout();
  await card.pendingLayoutSave;
  assert.equal(card.layoutSaveError,null);assert.equal(card.layoutRevisions.example_frame,2);
  assert.equal(card.flipped,false);assert.equal(card.layoutWrites.example_frame,undefined);
});
test('failed layout save blocks upload rather than using unsaved correction',async()=>{
  const {card,uploads}=fixture();card._hass.callApi=async()=>{throw Error('synthetic save failure');};
  card.flipped=true;card.rememberLayout();await card.pendingLayoutSave;await card.send();
  assert.equal(uploads.length,0);assert.match(card.shadowRoot.querySelector('.result').textContent,/synthetic save failure/);
});
test('source changed during async preparation is never uploaded',async()=>{
  const {card,uploads}=fixture();const original=card.decodeSource;
  card.decodeSource=async()=>{card.sourceURL='new-source';return original();};
  await card.send();assert.equal(uploads.length,0);
  assert.match(card.shadowRoot.querySelector('.result').textContent,/changed while preparing/);
});
test('concurrent sends are blocked while a request is active',async()=>{
  const {card,uploads}=fixture();card.uploadTransport='wifi';await card.send();assert.equal(uploads.length,0);
});

test('optional bin reminder toggle uses configured sensor and service',async()=>{
 const calls=[];const button={};const status={};const card=new Card();card.selectedFrame='example_frame';card.frames=[{id:'example_frame'}];
 card.shadowRoot={querySelector:s=>s==='.bin-toggle'?button:status};
 card._hass={states:{sensor_unused:{},'sensor.frame_bin_reminder_example_frame':{attributes:{enabled:false}}},callService:async(...args)=>calls.push(args)};
 await card.toggleBinReminder();assert.equal(JSON.stringify(calls),JSON.stringify([['frame_bin_reminder','set_enabled',{enabled:true}]]));assert.equal(button.disabled,false);
 card._hass.states.sensor_frame_bin_reminder_example_frame=undefined;
 card._hass.states['sensor.frame_bin_reminder_example_frame'].attributes.enabled=true;await card.toggleBinReminder();assert.equal(calls[1][2].enabled,false);
});
