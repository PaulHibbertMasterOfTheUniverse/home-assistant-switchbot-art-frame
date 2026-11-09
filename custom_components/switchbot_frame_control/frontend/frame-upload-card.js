class FrameUploadCard extends HTMLElement {
  setConfig(config) { this.config=config; this.render(); }
  set hass(hass) { this._hass=hass; if(!this.shadowRoot)this.render(); this.updateStatus(); if(!this.frames&&!this.loadingFrames&&!this.framesFailed)this.loadFrames(); }
  getCardSize() { return 6; }
  render() {
    if(!this.shadowRoot)this.attachShadow({mode:'open'});
    this.shadowRoot.innerHTML=`<ha-card header="Art frames"><style>
      .body{padding:0 20px 20px}input{display:block;margin:16px 0;width:100%}
      textarea{box-sizing:border-box;width:100%;min-height:110px;padding:12px;font:inherit;border-radius:8px;margin:8px 0;color:var(--primary-text-color);background:var(--card-background-color);border:1px solid var(--divider-color)}button{padding:12px 18px;border:0;border-radius:8px;background:var(--primary-color);color:var(--text-primary-color);font:inherit;cursor:pointer}
      button[aria-pressed="true"]{outline:3px solid var(--primary-text-color)}button:disabled{opacity:.5;cursor:wait}img{max-width:100%;max-height:240px;object-fit:contain;display:none;margin:12px auto}
      select{padding:10px;font:inherit;color:var(--primary-text-color);background:var(--card-background-color);border:1px solid var(--divider-color);border-radius:8px}.layout{display:flex;gap:12px;align-items:center;flex-wrap:wrap}p{line-height:1.5}.status{color:var(--secondary-text-color)}
      </style><div class="body"><label for="frame">Destination frame</label><select id="frame" aria-label="Destination frame" disabled><option>Loading frames…</option></select><p class="frame-result" role="status" aria-live="polite"></p><p class="connection-state" role="status"></p><div class="layout"><button class="mode-local">Bluetooth only</button><button class="mode-hybrid">Prefer Bluetooth</button><button class="mode-wifi">Wi-Fi only</button></div><p class="connection-note"></p><p class="notification-state"></p><div class="notification-controls" hidden><button class="toggle-notification">Toggle notification switch</button> <button class="show-baby">Show baby asleep picture</button> <button class="restore-normal">Restore normal slideshow</button></div><p>Choose a picture. Large images are automatically resized and converted to JPEG for the chosen frame orientation. Picture delivery uses the connection mode shown above. Wi-Fi mode uses SwitchBot’s cloud.</p>
      <label for="description">Describe a new picture</label><textarea id="description" maxlength="2048" placeholder="A cosy woodland cottage beneath a starry sky" aria-label="Picture description"></textarea><button class="generate">Generate picture</button><p class="generation" role="status" aria-live="polite"></p><p>Or upload a picture:</p><input type="file" accept="image/jpeg,image/png,image/webp" aria-label="Choose artwork">
      <div class="layout"><label for="orientation">Frame orientation</label><select id="orientation" aria-label="Frame orientation"><option value="landscape">Landscape — horizontal</option><option value="portrait">Portrait — vertical</option></select><button class="flip" aria-pressed="false">Rotate 180°</button></div><p class="orientation-note">Choose how the frame is standing. The preview shows the centre crop that will be sent.</p><img alt="Selected artwork preview"><button class="send" disabled>Send to frame</button>
      <div class="override-confirm" hidden role="alert"><p>The baby sleep picture is active. Replace it with this picture? The automation resumes when the waterfall switch changes again or you press Show baby asleep picture.</p><button class="override-cancel">Cancel</button> <button class="override-send">Send anyway</button></div>
      <div class="replace-confirm" hidden role="alert"><p class="replace-details"></p><button class="replace-cancel">Keep existing pictures</button> <button class="replace-send">Replace oldest and send</button></div><p role="status" aria-live="polite" class="result"></p><p class="status"></p><button class="repair">Reconnect after reset</button> <button class="archive" hidden>Download last replaced picture</button><p class="repair-result" role="status" aria-live="polite"></p><p class="backup-download" hidden><a class="save-backup">Save backup JPEG</a></p></div></ha-card>`;
    this.shadowRoot.querySelector('input').onchange=()=>this.loadFile();
    this.shadowRoot.querySelector('#orientation').onchange=()=>{this.rememberLayout();this.refreshPreview();};
    this.shadowRoot.querySelector('.flip').onclick=()=>{
      this.flipped=!this.flipped;this.shadowRoot.querySelector('.flip').setAttribute('aria-pressed',String(this.flipped));
      this.rememberLayout();this.refreshPreview();
    };
    this.shadowRoot.querySelector('#frame').onchange=()=>{this.selectedFrame=this.shadowRoot.querySelector('#frame').value;this.restoreLayout();if(this.preparedSource&&this.preparedBound<(this.frames?.find(f=>f.id===this.selectedFrame)?.width||1600))this.loadFile();else this.refreshPreview();this.shadowRoot.querySelector('.override-confirm').hidden=true;this.shadowRoot.querySelector('.result').textContent='';this.updateStatus();};
    this.shadowRoot.querySelector('.toggle-notification').onclick=()=>this.toggleNotification();
    this.shadowRoot.querySelector('.show-baby').onclick=()=>this.notification('show_baby');
    this.shadowRoot.querySelector('.restore-normal').onclick=()=>this.notification('restore_normal');
    this.shadowRoot.querySelector('.send').onclick=()=>this.send();
    this.shadowRoot.querySelector('.replace-cancel').onclick=()=>{this.replacement=null;this.shadowRoot.querySelector('.replace-confirm').hidden=true;this.shadowRoot.querySelector('.result').textContent='Cancelled. Existing pictures were kept.';};
    this.shadowRoot.querySelector('.replace-send').onclick=()=>{
      const proposal=this.replacement;
      if(!proposal||proposal.frame!==this.selectedFrame||proposal.source!==this.sourceURL||proposal.orientation!==this.shadowRoot.querySelector('#orientation').value||proposal.flipped!==!!this.flipped){this.shadowRoot.querySelector('.replace-confirm').hidden=true;this.shadowRoot.querySelector('.result').textContent='Picture or destination changed. Press Send to frame to review again.';return;}
      this.shadowRoot.querySelector('.replace-confirm').hidden=true;this.send(false,proposal.index);
    };
    this.shadowRoot.querySelector('.override-cancel').onclick=()=>{this.shadowRoot.querySelector('.override-confirm').hidden=true;this.shadowRoot.querySelector('.result').textContent='Cancelled. The baby picture was left unchanged.';};
    this.shadowRoot.querySelector('.override-send').onclick=()=>{this.shadowRoot.querySelector('.override-confirm').hidden=true;this.send(true,this.pendingReplaceIndex??null);};
    this.shadowRoot.querySelector('.generate').onclick=()=>this.generate();
    for(const mode of ['local','hybrid','wifi'])this.shadowRoot.querySelector('.mode-'+mode).onclick=()=>this.setMode(mode);
    this.shadowRoot.querySelector('.archive').onclick=()=>this.downloadArchive();
    this.shadowRoot.querySelector('.repair').onclick=()=>this.repair();this.updateStatus();
  }
  async loadFile(){
    const file=this.shadowRoot.querySelector('input').files[0],result=this.shadowRoot.querySelector('.result'),send=this.shadowRoot.querySelector('.send');
    this.releaseDecodedSource();if(this.previewURL)URL.revokeObjectURL(this.previewURL);
    this.generatedData=null;this.sourceURL=null;this.previewURL=null;this.preparedSource=false;
    send.disabled=true;this.shadowRoot.querySelector('img').style.display='none';
    this.shadowRoot.querySelector('.override-confirm').hidden=true;this.shadowRoot.querySelector('.replace-confirm').hidden=true;
    if(!file){result.textContent='Choose a picture.';return;}
    if(file.size>64*1024*1024){result.textContent='Choose an original picture smaller than 64 MB. Home Assistant will resize it before previewing.';return;}
    this.setFrameControlsBusy(true);this.shadowRoot.querySelector('.generate').disabled=true;
    const started=Date.now();result.textContent='Preparing picture in Home Assistant…';
    const progress=setInterval(()=>{result.textContent=`Preparing picture in Home Assistant… ${Math.floor((Date.now()-started)/1000)} seconds elapsed.`;},1000);
    try{
      const response=await this._hass.fetchWithAuth('/api/switchbot_frame_control/prepare?frame_id='+encodeURIComponent(this.targetFrame()),{method:'POST',headers:{'Content-Type':'application/octet-stream'},body:file});
      const prepared=await response.json();if(!response.ok)throw new Error(prepared.error||'Could not prepare the picture.');
      clearInterval(progress);
      if(this.shadowRoot.querySelector('input').files[0]!==file)return;
      this.preparedSource=true;this.preparedBound=prepared.bound;this.sourceURL='data:image/jpeg;base64,'+prepared.image;
      await this.refreshPreview();
    }catch(error){result.textContent=error.message||'Could not prepare the picture in Home Assistant.';}
    finally{clearInterval(progress);this.setFrameControlsBusy(false);this.shadowRoot.querySelector('.generate').disabled=false;}
  }
  rememberLayout(){
    if(!this.selectedFrame)return;
    const frame_id=this.selectedFrame;
    const layout={orientation:this.shadowRoot.querySelector('#orientation').value,flipped:!!this.flipped};
    this.layouts=this.layouts||{};
    if(JSON.stringify(this.layouts[frame_id])===JSON.stringify(layout))return;
    this.layoutWrites=this.layoutWrites||{};this.layoutWrites[frame_id]=layout;
    this.layouts[frame_id]=layout;this.savingLayout=true;const saveVersion=(this.layoutSaveVersion||0)+1;this.layoutSaveVersion=saveVersion;
    this.pendingLayoutSave=(this.pendingLayoutSave||Promise.resolve()).then(async()=>{
      try{
        await this._hass.callApi('POST','switchbot_frame_control/frames',{frame_id,layout});
        this.layoutSaveError=null;
      }catch(error){
        this.layoutSaveError=error.body?.error||error.message||'Could not save frame orientation';
        if(this.layoutWrites[frame_id]===layout)delete this.layoutWrites[frame_id];
        this.shadowRoot.querySelector('.result').textContent=this.layoutSaveError;
      }finally{if(saveVersion===this.layoutSaveVersion){this.savingLayout=false;this.updateStatus();}}
    });
  }
  restoreLayout(){
    const layout=this.layouts?.[this.selectedFrame]||{orientation:'landscape',flipped:false};
    this.shadowRoot.querySelector('#orientation').value=layout.orientation;this.flipped=layout.flipped;
    this.shadowRoot.querySelector('.flip').setAttribute('aria-pressed',String(this.flipped));
  }
  targetFrame(){
    if(!this.frames?.some(f=>f.id===this.selectedFrame))throw new Error('Choose a configured destination frame first.');
    return this.selectedFrame;
  }
  setFrameControlsBusy(busy){
    for(const selector of ['#frame','.repair','.show-baby','.restore-normal','.toggle-notification','.mode-local','.mode-hybrid','.mode-wifi'])this.shadowRoot.querySelector(selector).disabled=busy;
  }
  async loadFrames(){
    this.loadingFrames=true;const status=this.shadowRoot.querySelector('.frame-result');
    try{
      const response=await this._hass.callApi('GET','switchbot_frame_control/frames');
      if(!Array.isArray(response.frames)||!response.frames.length)throw new Error('No frames are configured.');
      this.frames=response.frames;
      this.layouts=Object.fromEntries(this.frames.map(frame=>[frame.id,frame.layout||{orientation:'landscape',flipped:false}]));
      const select=this.shadowRoot.querySelector('#frame');select.replaceChildren();
      for(const frame of this.frames){const option=document.createElement('option');option.value=frame.id;option.textContent=frame.name;select.append(option);}
      const wanted=this.config.frame_id||this.selectedFrame||this.frames[0].id;
      if(!this.frames.some(f=>f.id===wanted)){this.frames=null;throw new Error('The frame configured for this card was not found.');}
      this.selectedFrame=wanted;select.value=wanted;this.restoreLayout();select.disabled=false;status.textContent='';this.updateStatus();
    }catch(error){this.framesFailed=true;status.textContent=error.body?.error||error.message||'Could not load frames. Refresh this dashboard to retry.';}
    finally{this.loadingFrames=false;}
  }
  async setMode(mode){
    const status=this.shadowRoot.querySelector('.frame-result');this.setFrameControlsBusy(true);
    try{const frame_id=this.targetFrame();await this._hass.callService('switchbot_frame_control','set_connection_mode',{frame_id,mode});status.textContent='Connection mode saved for this frame.';}
    catch(error){status.textContent=error.body?.error||error.message||'Could not change connection mode.';}
    finally{this.setFrameControlsBusy(false);this.updateStatus();}
  }
  async toggleNotification(){
    const frame=this.frames?.find(f=>f.id===this.selectedFrame);if(!frame?.waterfall_entity)return;
    const status=this.shadowRoot.querySelector('.frame-result');this.setFrameControlsBusy(true);
    try{await this._hass.callService('homeassistant','toggle',{entity_id:frame.waterfall_entity});status.textContent='Selected frame’s notification switch updated.';}
    catch(error){status.textContent=error.message||'Could not update the notification switch.';}
    finally{this.setFrameControlsBusy(false);}
  }
  async notification(service){
    const status=this.shadowRoot.querySelector('.frame-result');this.setFrameControlsBusy(true);
    try{const frame_id=this.targetFrame();this.shadowRoot.querySelector('.send').disabled=true;status.textContent='Updating the selected frame…';await this._hass.callService('switchbot_frame_control',service,{frame_id});status.textContent='Selected frame updated.';}
    catch(error){status.textContent=error.message||'Could not update the selected frame.';}
    finally{this.setFrameControlsBusy(false);this.refreshPreview();}
  }
  updateStatus(){
    if(!this.shadowRoot||!this._hass)return;
    const frame=this.frames?.find(f=>f.id===this.selectedFrame);
    this.shadowRoot.querySelector('.notification-controls').hidden=!frame;
    this.shadowRoot.querySelector('.show-baby').hidden=!frame?.notification_configured;
    const state=frame?this._hass.states[frame.status_entity]:null;
    this.shadowRoot.querySelector('.archive').hidden=!state?.attributes?.archive_available;
    const savedLayout=state?.attributes?.layout;
    if(savedLayout&&this.layoutWrites?.[this.selectedFrame]&&JSON.stringify(savedLayout)===JSON.stringify(this.layoutWrites[this.selectedFrame]))delete this.layoutWrites[this.selectedFrame];
    if(savedLayout&&!this.layoutWrites?.[this.selectedFrame]&&!this.savingLayout&&!this.uploadTransport&&JSON.stringify(this.layouts?.[this.selectedFrame])!==JSON.stringify(savedLayout)){this.layouts=this.layouts||{};this.layouts[this.selectedFrame]=savedLayout;this.restoreLayout();this.refreshPreview();}
    const mode=state?.attributes?.connection_mode||'local';
    const labels={local:'Bluetooth only',hybrid:'Prefer Bluetooth; Wi-Fi/cloud when needed',wifi:'Wi-Fi only — uses SwitchBot cloud'};
    this.shadowRoot.querySelector('.connection-state').textContent=frame?`${frame.model==='frame1'?'Original AI Art Frame':'AI Art Frame 2'}${frame.panel_size?' · '+frame.panel_size+' inch':''} · ${labels[mode]||mode}`:'';
    for(const value of ['local','hybrid','wifi'])this.shadowRoot.querySelector('.mode-'+value).setAttribute('aria-pressed',String(mode===value));
    this.shadowRoot.querySelector('.connection-note').textContent=frame?.model==='frame1'?'Original frame: stored pictures can be selected over Bluetooth. New pictures require Wi-Fi and SwitchBot cloud.':'Bluetooth-only mode delivers pictures locally. Wi-Fi mode sends the picture to SwitchBot cloud and needs internet access.';
    const trigger=frame?.waterfall_entity?this._hass.states[frame.waterfall_entity]:null;
    this.shadowRoot.querySelector('.toggle-notification').hidden=!trigger;
    this.shadowRoot.querySelector('.toggle-notification').textContent=trigger?`Turn ${trigger.attributes.friendly_name||'notification switch'} ${trigger.state==='on'?'off':'on'}`:'Toggle notification switch';
    this.shadowRoot.querySelector('.notification-state').textContent=trigger?`${trigger.attributes.friendly_name||'Notification switch'}: ${trigger.state}`:'';
    this.shadowRoot.querySelector('.status').textContent=this.uploadTransport==='wifi'?'Sending picture via Wi-Fi and SwitchBot cloud…':state?(state.attributes.error||state.attributes.last_action||'Ready'):'Controller starting';
  }
  async downloadArchive(){
    const status=this.shadowRoot.querySelector('.repair-result');
    try{
      const backup=await this._hass.callApi('POST','switchbot_frame_control/archive',{frame_id:this.targetFrame()});
      if(this.backupURL)URL.revokeObjectURL(this.backupURL);
      const raw=atob(backup.image),bytes=Uint8Array.from(raw,c=>c.charCodeAt(0));
      this.backupURL=URL.createObjectURL(new Blob([bytes],{type:'image/jpeg'}));
      const link=this.shadowRoot.querySelector('.save-backup');link.href=this.backupURL;link.download=backup.filename;
      this.shadowRoot.querySelector('.backup-download').hidden=false;
      status.textContent='Private backup is ready. Press Save backup JPEG below.';
    }catch(error){status.textContent=error.body?.error||error.message||'Could not download the backup.';}
  }
  async repair(){
    const button=this.shadowRoot.querySelector('.repair'),status=this.shadowRoot.querySelector('.repair-result');
    this.setFrameControlsBusy(true);status.textContent='Refreshing the connection and checking the frame…';
    try{const frame_id=this.targetFrame();await this._hass.callService('switchbot_frame_control','repair_connection',{frame_id});status.textContent='Connection checked. See the controller status above.';}
    catch(error){status.textContent=error.message||'Could not reconnect. Check the frame is paired in SwitchBot and within Bluetooth range.';}
    finally{this.setFrameControlsBusy(false);}
  }
  async generate(){
    const prompt=this.shadowRoot.querySelector('textarea').value.trim();
    const button=this.shadowRoot.querySelector('.generate'),send=this.shadowRoot.querySelector('.send');
    const status=this.shadowRoot.querySelector('.generation');
    if(!prompt){status.textContent='Describe the picture you want first.';return;}
    button.disabled=true;button.textContent='Creating picture…';button.setAttribute('aria-busy','true');send.disabled=true;this.generatedData=null;
    const started=Date.now();status.textContent='Creating your picture… This can take up to two minutes.';
    const progress=setInterval(()=>{status.textContent=`Creating your picture… ${Math.floor((Date.now()-started)/1000)} seconds elapsed. Waiting for the image generator.`;},1000);
    try{
      const response=await this._hass.callApi('POST','switchbot_frame_control/generate',{prompt,frame_id:this.targetFrame()});
      this.generatedData=response.image;this.preparedSource=false;
      this.shadowRoot.querySelector('input').value='';
      this.sourceURL='data:image/jpeg;base64,'+response.image;await this.refreshPreview();send.disabled=false;
      status.textContent='Your picture is ready. Send it to the frame, or change the description and generate another.';
    }catch(error){status.textContent=error.body?.error||error.body?.message||error.message||'Could not generate the picture.';}
    finally{clearInterval(progress);button.disabled=false;button.textContent='Generate picture';button.removeAttribute('aria-busy');}
  }
  async send(confirmed=false,replaceIndex=null){
    const file=this.shadowRoot.querySelector('input').files[0];
    if(!file&&!this.generatedData){this.shadowRoot.querySelector('.result').textContent='Choose a picture or generate one before sending.';return;}
    const result=this.shadowRoot.querySelector('.result'),button=this.shadowRoot.querySelector('.send');
    this.shadowRoot.querySelector('.replace-confirm').hidden=true;
    const destination=this.frames?.find(f=>f.id===this.selectedFrame);
    if(!destination){result.textContent='Choose a configured destination frame first.';return;}
    const frameState=this._hass.states?.[destination.status_entity];
    const mode=frameState?.attributes?.connection_mode||'local';
    const wifi=mode==='wifi'||destination.model==='frame1';
    const override=frameState?.attributes?.baby_notification_active===true;
    if(override&&confirmed!==true){this.pendingReplaceIndex=replaceIndex;this.shadowRoot.querySelector('.override-confirm').hidden=false;return;}
    this.uploadTransport=wifi?'wifi':'bluetooth';this.updateStatus();
    button.disabled=true;this.setFrameControlsBusy(true);this.shadowRoot.querySelector('#orientation').disabled=true;this.shadowRoot.querySelector('.flip').disabled=true;this.shadowRoot.querySelector('input').disabled=true;this.shadowRoot.querySelector('.generate').disabled=true;result.textContent='Resizing and converting picture…';
    try{
      await this.pendingLayoutSave;
      if(this.layoutSaveError)throw new Error(this.layoutSaveError);
      const prepared=await this.preparePicture();
      const data=prepared.transport.toDataURL('image/jpeg',0.92).split(',')[1];
      prepared.transport.width=prepared.transport.height=0;prepared.preview.width=prepared.preview.height=0;
      result.textContent=wifi?'Sending picture via Wi-Fi and SwitchBot cloud…':mode==='hybrid'?'Sending picture; checking Bluetooth or Wi-Fi/cloud delivery…':'Sending prepared picture over Bluetooth…';
      const response=await this._hass.callApi('POST','switchbot_frame_control/upload',{image:data,override_baby:override,frame_id:destination.id,...(replaceIndex!==null?{replace_index:replaceIndex}:{})});
      result.textContent=response.local_storage_verified?'Picture stored and selected by the frame. Allow the screen to finish refreshing.':response.accepted?'SwitchBot accepted the Wi-Fi/cloud request. Delivery and physical screen are not yet verified.':'Please check the controller status.';
    }catch(error){
      result.textContent=error.body?.error||error.message||'Could not send the picture. Check the controller status.';
      const candidate=error.body?.replacement;
      if(candidate&&Number.isInteger(candidate.index)){
        this.replacement={...candidate,frame:destination.id,source:this.sourceURL,orientation:this.shadowRoot.querySelector('#orientation').value,flipped:!!this.flipped};
        const date=new Date(candidate.created_at).toLocaleDateString();
        this.shadowRoot.querySelector('.replace-details').textContent=`${destination.name} is full. Replace its oldest stored artwork (picture ${candidate.index}, added ${date}) with this picture? The old picture will leave the frame. If its cloud slot must also be freed, a private backup will be saved in Home Assistant; use Download last replaced picture to recover it. The baby notification picture is protected.`;
        this.shadowRoot.querySelector('.replace-confirm').hidden=false;
      }
    }
    finally{this.uploadTransport=null;this.updateStatus();button.disabled=false;this.setFrameControlsBusy(false);this.shadowRoot.querySelector('#orientation').disabled=false;this.shadowRoot.querySelector('.flip').disabled=false;this.shadowRoot.querySelector('input').disabled=false;this.shadowRoot.querySelector('.generate').disabled=false;}
  }
  releaseDecodedSource(){
    if(this.decodedSource?.close)this.decodedSource.close();
    else if(this.decodedSource)this.decodedSource.src='';
    this.decodedSource=null;this.decodedSourceKey=null;
  }
  async decodeSource(){
    const frame=this.frames?.find(f=>f.id===this.selectedFrame);
    const width=frame?.width||1600;
    const key=this.sourceURL+'|'+width;
    if(this.decodedSourceKey===key&&this.decodedSource)return this.decodedSource;
    if(this.decodeKey===key&&this.decodePromise)return this.decodePromise;
    const source=this.sourceURL,file=this.preparedSource?null:this.shadowRoot.querySelector('input').files[0];
    this.decodeKey=key;
    this.decodePromise=(async()=>{
      let image;
      if(file&&typeof createImageBitmap==='function'){
        // Decode camera photos straight to a bounded working bitmap, once.
        // Do not retain a full-resolution HTML image for every preview/send.
        image=await createImageBitmap(file,{resizeWidth:width,resizeQuality:'high'});
      }else{
        image=new Image();image.src=source;await image.decode();
      }
      if(source!==this.sourceURL){if(image.close)image.close();throw new Error('Picture changed while loading');}
      this.releaseDecodedSource();this.decodedSource=image;this.decodedSourceKey=key;
      return image;
    })();
    try{return await this.decodePromise;}finally{if(this.decodeKey===key){this.decodePromise=null;this.decodeKey=null;}}
  }
  async preparePicture(previewOnly=false){
    const image=await this.decodeSource();
    const portrait=this.shadowRoot.querySelector('#orientation').value==='portrait';
    const frame=this.frames?.find(f=>f.id===this.selectedFrame);const wide=frame?.width||1600,tall=frame?.height||1200;
    const scale=previewOnly?Math.min(1,600/Math.max(wide,tall)):1;
    const canvas=document.createElement('canvas');canvas.width=Math.round((portrait?tall:wide)*scale);canvas.height=Math.round((portrait?wide:tall)*scale);
    const ctx=canvas.getContext('2d'),ratio=canvas.width/canvas.height;
    const sourceWidth=image.naturalWidth||image.width,sourceHeight=image.naturalHeight||image.height;
    let width=sourceWidth,height=sourceHeight;
    if(width/height>ratio)width=height*ratio;else height=width/ratio;
    ctx.fillStyle='#fff';ctx.fillRect(0,0,canvas.width,canvas.height);
    if(this.flipped){ctx.translate(canvas.width,canvas.height);ctx.rotate(Math.PI);}
    ctx.drawImage(image,(sourceWidth-width)/2,(sourceHeight-height)/2,width,height,0,0,canvas.width,canvas.height);
    // The server encoder accepts landscape and rotates it into native panel order.
    // Counter-rotate portrait here, leaving its final native pixels upright.
    let transport=canvas;
    if(portrait&&!previewOnly){
      transport=document.createElement('canvas');transport.width=wide;transport.height=tall;
      const out=transport.getContext('2d');out.translate(0,tall);out.rotate(-Math.PI/2);out.drawImage(canvas,0,0);
    }
    return {preview:canvas,transport};
  }
  async refreshPreview(){
    const version=this.previewVersion=(this.previewVersion||0)+1;
    const send=this.shadowRoot.querySelector('.send'),img=this.shadowRoot.querySelector('img');send.disabled=true;
    this.shadowRoot.querySelector('.override-confirm').hidden=true;this.shadowRoot.querySelector('.replace-confirm').hidden=true;this.replacement=null;img.style.display='none';
    if(!this.sourceURL){img.style.display='none';return;}
    try{
      const prepared=await this.preparePicture(true);if(version!==this.previewVersion){prepared.preview.width=prepared.preview.height=0;return;}
      img.src=prepared.preview.toDataURL('image/jpeg',0.88);prepared.preview.width=prepared.preview.height=0;img.style.display='block';send.disabled=false;
      if(this.shadowRoot.querySelector('.result').textContent==='Reading selected picture…')this.shadowRoot.querySelector('.result').textContent='Selected picture is ready. Press Send to frame.';
    }catch(error){if(version===this.previewVersion)this.shadowRoot.querySelector('.result').textContent='Could not read this picture. Please choose another image.';}
  }
  disconnectedCallback(){if(this.backupURL)URL.revokeObjectURL(this.backupURL);this.releaseDecodedSource();if(this.previewURL)URL.revokeObjectURL(this.previewURL);}
}
if(!customElements.get('frame-upload-card'))customElements.define('frame-upload-card',FrameUploadCard);
window.customCards=window.customCards||[];
window.customCards.push({type:'frame-upload-card',name:'Frame picture upload',description:'Art Frame 1 and 2: Bluetooth controls and optional Wi-Fi/cloud delivery.'});
