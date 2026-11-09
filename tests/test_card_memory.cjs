const fs=require('fs'),vm=require('vm'),assert=require('assert');
let decodes=0,closed=0,canvases=[];
class Canvas{getContext(){return {fillRect(){},translate(){},rotate(){},drawImage(){}}} }
const ctx={HTMLElement:class{},customElements:{define(){},get(){return false}},window:{},document:{createElement(){const c=new Canvas();canvases.push(c);return c;}},createImageBitmap:async(file,options)=>{decodes++;return {width:options.resizeWidth,height:options.resizeWidth*4/3,close(){closed++;}}}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(require('path').join(__dirname,'../custom_components/switchbot_frame_control/frontend/frame-upload-card.js'),'utf8')+';globalThis.Card=FrameUploadCard',ctx);
(async()=>{const c=new ctx.Card();c.frames=[{id:'large',width:2560,height:1440}];c.selectedFrame='large';c.sourceURL='test-source';const file={};c.shadowRoot={querySelector:q=>q==='input'?{files:[file]}:{value:'portrait'}};
let p=await c.preparePicture(true);assert.equal(Math.max(p.preview.width,p.preview.height),600);assert.equal(canvases.length,1);assert.equal(decodes,1);
let full=await c.preparePicture();assert.equal(full.transport.width,2560);assert.equal(full.transport.height,1440);assert.equal(decodes,1);
c.releaseDecodedSource();assert.equal(closed,1);assert.equal(c.decodedSource,null);console.log('Preview is bounded to 600 px, portrait transport remains 2560x1440, image decodes once and bitmap is released.');})().catch(e=>{console.error(e);process.exit(1)});
