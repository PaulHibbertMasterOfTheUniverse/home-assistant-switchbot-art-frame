// Release 20261120-stale-error: generic failures scoped to frame/session action; historical diagnostics collapsed.
class FrameUploadCard extends HTMLElement {
  setConfig(config) { this.config=config; this.render(); }
  set hass(hass) { this._hass=hass; if(!this.shadowRoot)this.render(); this.updateStatus(); if(!this.frames&&!this.loadingFrames&&!this.framesFailed)this.loadFrames(); if(!this.galleryLoaded&&!this.galleryLoading)this.loadGallery(); }
  getCardSize() { return 6; }
  render() {
    if(!this.shadowRoot)this.attachShadow({mode:'open'});
    this.shadowRoot.innerHTML=`<ha-card header="Art frames"><style>
      .body{padding:0 20px 20px}input{display:block;margin:16px 0;width:100%}
      textarea{box-sizing:border-box;width:100%;min-height:110px;padding:12px;font:inherit;border-radius:8px;margin:8px 0;color:var(--primary-text-color);background:var(--card-background-color);border:1px solid var(--divider-color)}button{padding:12px 18px;border:0;border-radius:8px;background:var(--primary-color);color:var(--text-primary-color);font:inherit;cursor:pointer}
      button[aria-pressed="true"]{outline:3px solid var(--primary-text-color)}button:disabled{opacity:.5;cursor:wait}img{max-width:100%;max-height:240px;object-fit:contain;display:none;margin:12px auto}
      select{padding:10px;font:inherit;color:var(--primary-text-color);background:var(--card-background-color);border:1px solid var(--divider-color);border-radius:8px}.layout{display:flex;gap:12px;align-items:center;flex-wrap:wrap}p{line-height:1.5}.status{color:var(--secondary-text-color)}
      .send-progress-wrap{display:flex;align-items:center;gap:10px;margin:18px 0}.send-progress-wrap[hidden]{display:none}.send-progress{height:14px;flex:1;overflow:hidden;border-radius:9px;background:var(--divider-color,#ddd)}.send-progress-fill{height:100%;width:40%;border-radius:inherit;background:var(--primary-color,#03a9f4);animation:frame-progress 1.5s ease-in-out infinite}.send-progress[data-complete="true"] .send-progress-fill{width:100%;animation:none;background:var(--success-color,#238636)}.send-check{color:var(--success-color,#238636);font-size:22px}.progress-sr{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}.send-error,.cleanup-error,.result,.status{color:var(--error-color,#b3261e)}.send-error:empty,.cleanup-error:empty,.result:empty,.status:empty{display:none}@keyframes frame-progress{from{transform:translateX(-110%)}to{transform:translateX(350%)}}@media(prefers-reduced-motion:reduce){.send-progress:not([data-complete="true"]) .send-progress-fill{animation:none;transform:translateX(75%)}}
      </style><div class="body"><label for="frame">Destination frame</label><select id="frame" aria-label="Destination frame" disabled><option>Loading frames…</option></select><p class="frame-result" role="status" aria-live="polite"></p><p class="connection-state" role="status"></p><div class="layout"><button class="mode-local">Bluetooth only</button><button class="mode-hybrid">Prefer Bluetooth</button><button class="mode-wifi">Wi-Fi only</button></div><p class="connection-note"></p><p class="notification-state"></p><div class="notification-controls" hidden><button class="show-baby">Show baby asleep picture</button> <button class="restore-normal">Restore normal slideshow</button></div><p>Choose a picture. Large images are automatically resized and converted to JPEG for the chosen frame orientation. Picture delivery uses the connection mode shown above. Wi-Fi mode uses SwitchBot’s cloud.</p>
      <label for="description">Describe a new picture</label><textarea id="description" maxlength="2048" placeholder="A cosy woodland cottage beneath a starry sky" aria-label="Picture description"></textarea><button class="generate">Generate picture</button><p class="generation" role="status" aria-live="polite"></p><p>Or upload a picture:</p><input type="file" accept="image/jpeg,image/png,image/webp" aria-label="Choose artwork">
      <div class="layout"><label for="orientation">Frame orientation</label><select id="orientation" aria-label="Frame orientation"><option value="landscape">Landscape — horizontal</option><option value="portrait">Portrait — vertical</option></select></div><details><summary>Advanced: frame mounting calibration</summary><p>Saved for this frame, not a photo edit. Changes affect transport only; the preview stays in photo orientation.</p><button class="flip" aria-pressed="false">Mounting correction: 180°</button></details><p class="orientation-note">Choose how the frame is standing. The preview shows the photo centre crop before hardware mounting correction.</p><img alt="Selected artwork preview"><button class="send" disabled>Send to frame</button>
      <div class="override-confirm" hidden role="alert"><p>The baby sleep picture is active. Replace it with this picture? The automation resumes when the waterfall switch changes again or you press Show baby asleep picture.</p><button class="override-cancel">Cancel</button> <button class="override-send">Send anyway</button></div>
      <div class="replace-confirm" hidden role="alert"><p class="replace-details"></p><button class="replace-cancel">Keep existing pictures</button> <button class="replace-send">Replace oldest and send</button></div><p role="status" aria-live="polite" class="result"></p><p class="status"></p><button class="repair">Reconnect after reset</button> <button class="archive" hidden>Download last replaced picture</button><p class="repair-result" role="status" aria-live="polite"></p><p class="backup-download" hidden><a class="save-backup">Save backup JPEG</a></p><section class="bin-controls" hidden><h3>Bin-day reminders</h3><button class="bin-toggle" aria-pressed="false">Enable bin reminders</button><p class="bin-status" role="status" aria-live="polite"></p></section><details class="gallery-section"><summary>Home Assistant artwork gallery — expand</summary><p>Saved privately in Home Assistant. Choose artwork below, then press Send to frame. Automations can use each artwork ID.</p><label for="gallery-name">Artwork name</label><input id="gallery-name" type="text" maxlength="100" placeholder="Give this picture a name"><button class="gallery-save">Save current picture to gallery</button> <button class="gallery-refresh">Refresh gallery</button><button class="gallery-import">Add bin artwork</button><p class="gallery-status" role="status" aria-live="polite"></p><div class="gallery-items" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:12px"></div><p class="gallery-undo" hidden><button class="gallery-restore">Undo last deletion</button></p></details></div></ha-card>`;
    this.shadowRoot.querySelector('.result').insertAdjacentHTML('beforebegin','<div class="send-progress-wrap" hidden><div class="send-progress" role="progressbar" aria-label="Image delivery" aria-valuemin="0" aria-valuemax="100"><div class="send-progress-fill"></div></div><span class="send-check" aria-hidden="true" hidden>✓</span><span class="progress-sr" role="status" aria-live="polite"></span></div><p class="send-error" role="alert"></p>');
    this.shadowRoot.querySelector('.status').insertAdjacentHTML('afterend','<p class="cleanup-error" role="alert"></p>');
    this.shadowRoot.querySelector('.status').setAttribute('role','alert');
    this.shadowRoot.querySelector('.status').insertAdjacentHTML('afterend','<details class="previous-operation" hidden><summary>Previous operation — diagnostics</summary><p class="previous-operation-details"></p></details>');
    this.shadowRoot.querySelector('.result').setAttribute('role','alert');
    this.shadowRoot.querySelector('.bin-toggle').onclick=()=>this.toggleBinReminder();
    this.shadowRoot.querySelector('.gallery-import').onclick=()=>this.importBinArtwork();
    this.shadowRoot.querySelector('.gallery-restore').onclick=()=>this.restoreGallery();
    this.shadowRoot.querySelector('input').onchange=()=>this.loadFile();
    this.shadowRoot.querySelector('#orientation').onchange=()=>{this.rememberLayout();this.refreshPreview();};
    this.shadowRoot.querySelector('.flip').onclick=()=>{
      this.flipped=!this.flipped;this.shadowRoot.querySelector('.flip').setAttribute('aria-pressed',String(this.flipped));
      this.rememberLayout();this.refreshPreview();
    };
    this.shadowRoot.querySelector('#frame').onchange=()=>{this.selectedFrame=this.shadowRoot.querySelector('#frame').value;this.restoreLayout();if(this.preparedSource&&this.preparedBound<(this.frames?.find(f=>f.id===this.selectedFrame)?.width||1600))this.loadFile();else this.refreshPreview();this.shadowRoot.querySelector('.override-confirm').hidden=true;for(const selector of ['.result','.frame-result','.repair-result'])this.shadowRoot.querySelector(selector).textContent='';this.shadowRoot.querySelector('.previous-operation').open=false;this.updateStatus();};
    this.shadowRoot.querySelector('.show-baby').onclick=()=>this.notification('show_baby');
    this.shadowRoot.querySelector('.restore-normal').onclick=()=>this.notification('restore_normal');
    this.shadowRoot.querySelector('.send').onclick=()=>this.send();
    this.shadowRoot.querySelector('.replace-cancel').onclick=()=>{this.replacement=null;this.shadowRoot.querySelector('.replace-confirm').hidden=true;this.clearSendFeedback();};
    this.shadowRoot.querySelector('.replace-send').onclick=()=>{
      const proposal=this.replacement;
      if(!proposal||proposal.frame!==this.selectedFrame||proposal.source!==this.sourceURL||proposal.orientation!==this.shadowRoot.querySelector('#orientation').value||proposal.flipped!==!!this.flipped){this.shadowRoot.querySelector('.replace-confirm').hidden=true;this.shadowRoot.querySelector('.result').textContent='Picture or destination changed. Press Send to frame to review again.';return;}
      this.shadowRoot.querySelector('.replace-confirm').hidden=true;this.send(false,proposal.index);
    };
    this.shadowRoot.querySelector('.override-cancel').onclick=()=>{this.shadowRoot.querySelector('.override-confirm').hidden=true;this.clearSendFeedback();};
    this.shadowRoot.querySelector('.override-send').onclick=()=>{this.shadowRoot.querySelector('.override-confirm').hidden=true;this.send(true,this.pendingReplaceIndex??null);};
    this.shadowRoot.querySelector('.generate').onclick=()=>this.generate();
    for(const mode of ['local','hybrid','wifi'])this.shadowRoot.querySelector('.mode-'+mode).onclick=()=>this.setMode(mode);
    this.shadowRoot.querySelector('.archive').onclick=()=>this.downloadArchive();
    this.shadowRoot.querySelector('.repair').onclick=()=>this.repair();this.shadowRoot.querySelector('.gallery-save').onclick=()=>this.saveGallery();this.shadowRoot.querySelector('.gallery-refresh').onclick=()=>{this.galleryLoaded=false;this.loadGallery();};this.updateStatus();
  }
  async importBinArtwork(){
    const status=this.shadowRoot.querySelector('.gallery-status');
    try{await this._hass.callApi('POST','frame_art_gallery',{action:'import_bin_artwork'});await this.loadGallery();}
    catch(error){status.textContent=error.body?.error||error.message||'Could not add bin artwork.';}
  }
  async toggleBinReminder(){
    const sensor=this._hass.states?.['sensor.frame_bin_reminder_'+this.targetFrame()];
    if(!sensor)throw new Error('Configure the optional bin reminder first.');
    const button=this.shadowRoot.querySelector('.bin-toggle');button.disabled=true;
    try{await this._hass.callService('frame_bin_reminder','set_enabled',{enabled:!sensor.attributes.enabled});}
    catch(error){this.shadowRoot.querySelector('.bin-status').textContent=error.message||'Could not change bin reminders.';}
    finally{button.disabled=false;}
  }
  async loadGallery(){
    if(!this._hass||this.galleryLoading)return;
    this.galleryLoading=true;
    const status=this.shadowRoot.querySelector('.gallery-status');
    try{
      const result=await this._hass.callApi('GET','frame_art_gallery');
      const target=this.shadowRoot.querySelector('.gallery-items');target.replaceChildren();
      for(const artwork of result.images){
        const box=document.createElement('div'),button=document.createElement('button'),image=document.createElement('img'),label=document.createElement('span'),code=document.createElement('small');
        image.src='data:image/jpeg;base64,'+artwork.thumbnail;image.alt=artwork.name;image.style.cssText='display:block;width:100%;height:110px;object-fit:contain;margin:0 0 8px';
        label.textContent=artwork.name;button.append(image,label);button.style.width='100%';button.onclick=()=>this.chooseGallery(artwork);
        code.textContent=artwork.id;code.style.cssText='display:block;overflow-wrap:anywhere;user-select:all;margin-top:6px';
        const download=document.createElement('button'),remove=document.createElement('button'),confirm=document.createElement('div'),yes=document.createElement('button'),cancel=document.createElement('button');
        download.textContent='Download';download.onclick=()=>this.downloadGallery(artwork,download);
        remove.textContent='Delete';confirm.hidden=true;confirm.setAttribute('role','alert');
        const warning=document.createElement('p');warning.textContent='Move '+artwork.name+' to gallery trash? Frame and cloud pictures are unchanged.';
        yes.textContent='Move to trash';cancel.textContent='Cancel';
        remove.onclick=()=>{confirm.hidden=false;};cancel.onclick=()=>{confirm.hidden=true;};
        yes.onclick=()=>this.trashGallery(artwork,yes);
        confirm.append(warning,yes,cancel);box.append(button,code,download,remove,confirm);target.append(box);
      }
      status.textContent=result.images.length?`${result.images.length} saved pictures. Automation action: frame_art_gallery.send_image.`:'Your gallery is empty. Upload or generate a picture, then save it here.';
      this.galleryLoaded=true;
    }catch(error){status.textContent=error.body?.error||error.message||'Could not load the gallery.';this.galleryLoaded=true;}
    finally{this.galleryLoading=false;}
  }
  async downloadGallery(artwork,button){
    const status=this.shadowRoot.querySelector('.gallery-status');button.disabled=true;
    try{
      const response=await this._hass.fetchWithAuth('/api/frame_art_gallery/artwork/'+encodeURIComponent(artwork.id));
      if(!response.ok)throw new Error('Could not download artwork.');
      const blob=await response.blob(),url=URL.createObjectURL(blob),link=document.createElement('a');
      link.href=url;link.download=response.headers.get('Content-Disposition')?.match(/filename="([^"]+)"/)?.[1]||'Artwork.jpg';
      document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);
      status.textContent='Downloaded full-resolution original: '+link.download;
    }catch(error){status.textContent=error.message||'Download failed.';}finally{button.disabled=false;}
  }
  async trashGallery(artwork,button){
    const status=this.shadowRoot.querySelector('.gallery-status');button.disabled=true;
    try{
      await this._hass.callApi('POST','frame_art_gallery/artwork/'+encodeURIComponent(artwork.id),{action:'trash',confirm:true});
      this.lastTrashed=artwork;await this.loadGallery();this.shadowRoot.querySelector('.gallery-undo').hidden=false;
      status.textContent=artwork.name+' moved to recoverable gallery trash. Frame/cloud unchanged.';
    }catch(error){status.textContent=error.body?.error||error.message||'Delete failed.';}finally{button.disabled=false;}
  }
  async restoreGallery(){
    if(!this.lastTrashed)return;
    const status=this.shadowRoot.querySelector('.gallery-status'),button=this.shadowRoot.querySelector('.gallery-restore');button.disabled=true;
    try{
      await this._hass.callApi('POST','frame_art_gallery/artwork/'+encodeURIComponent(this.lastTrashed.id),{action:'restore',confirm:true});
      await this.loadGallery();this.shadowRoot.querySelector('.gallery-undo').hidden=true;this.lastTrashed=null;status.textContent='Artwork restored.';
    }catch(error){status.textContent=error.body?.error||error.message||'Restore failed.';}finally{button.disabled=false;}
  }
  async saveGallery(){
    const status=this.shadowRoot.querySelector('.gallery-status'),button=this.shadowRoot.querySelector('.gallery-save');
    if(!this.sourceURL){status.textContent='Upload, generate or select a picture first.';return;}
    button.disabled=true;status.textContent='Saving picture in Home Assistant…';
    try{
      const image=await this.decodeSource(),canvas=document.createElement('canvas');
      canvas.width=image.naturalWidth||image.width;canvas.height=image.naturalHeight||image.height;
      const scale=Math.min(1,2560/Math.max(canvas.width,canvas.height));canvas.width=Math.round(canvas.width*scale);canvas.height=Math.round(canvas.height*scale);
      canvas.getContext('2d').drawImage(image,0,0,canvas.width,canvas.height);
      const encoded=canvas.toDataURL('image/jpeg',0.92).split(',')[1];canvas.width=canvas.height=0;
      const saved=await this._hass.callApi('POST','frame_art_gallery',{image:encoded,name:this.shadowRoot.querySelector('#gallery-name').value||'Saved artwork'});
      await this.loadGallery();status.textContent='Saved locally. Artwork ID: '+saved.id;
    }catch(error){status.textContent=error.body?.error||error.message||'Could not save the artwork.';}
    finally{button.disabled=false;}
  }
  async chooseGallery(artwork){
    const status=this.shadowRoot.querySelector('.gallery-status');status.textContent='Loading '+artwork.name+'…';
    try{
      const result=await this._hass.callApi('GET','frame_art_gallery/image/'+encodeURIComponent(artwork.id));
      this.clearSendFeedback();
      this.releaseDecodedSource();this.shadowRoot.querySelector('input[type=file]').value='';
      this.generatedData=result.image;this.preparedSource=true;this.preparedBound=2560;this.sourceURL='data:image/jpeg;base64,'+result.image;
      this.shadowRoot.querySelector('#gallery-name').value=artwork.name;await this.refreshPreview();
      status.textContent=artwork.name+' selected. Press Send to frame. Automation artwork ID: '+artwork.id;
    }catch(error){status.textContent=error.body?.error||error.message||'Could not load the artwork.';}
  }
  async loadFile(){
    const file=this.shadowRoot.querySelector('input').files[0],result=this.shadowRoot.querySelector('.result'),send=this.shadowRoot.querySelector('.send');
    this.clearSendFeedback();this.releaseDecodedSource();if(this.previewURL)URL.revokeObjectURL(this.previewURL);
    this.generatedData=null;this.sourceURL=null;this.previewURL=null;this.preparedSource=false;
    send.disabled=true;this.shadowRoot.querySelector('img').style.display='none';
    this.shadowRoot.querySelector('.override-confirm').hidden=true;this.shadowRoot.querySelector('.replace-confirm').hidden=true;
    if(!file){result.textContent='';return;}
    if(file.size>64*1024*1024){result.textContent='Choose an original picture smaller than 64 MB. Home Assistant will resize it before previewing.';return;}
    this.setFrameControlsBusy(true);this.shadowRoot.querySelector('.generate').disabled=true;
    result.textContent='';const preparation={frame:this.selectedFrame};this.sourcePreparation=preparation;this.updateStatus();
    try{
      const response=await this._hass.fetchWithAuth('/api/switchbot_frame_control/prepare?frame_id='+encodeURIComponent(this.targetFrame()),{method:'POST',headers:{'Content-Type':'application/octet-stream'},body:file});
      const prepared=await response.json();if(!response.ok)throw new Error(prepared.error||'Could not prepare the picture.');
      if(this.shadowRoot.querySelector('input').files[0]!==file)return;
      this.preparedSource=true;this.preparedBound=prepared.bound;this.sourceURL='data:image/jpeg;base64,'+prepared.image;
      await this.refreshPreview();
    }catch(error){result.textContent=error.message||'Could not prepare the picture in Home Assistant.';}
    finally{if(this.sourcePreparation===preparation)this.sourcePreparation=null;this.setFrameControlsBusy(false);this.shadowRoot.querySelector('.generate').disabled=false;this.updateStatus();}
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
      const action=this.beginFrameAction(frame_id,'Save layout');
      try{
        const response=await this._hass.callApi('POST','switchbot_frame_control/frames',{frame_id,layout,expected_revision:this.layoutRevisions?.[frame_id]||0});
        this.layoutRevisions=this.layoutRevisions||{};
        this.layoutRevisions[frame_id]=Math.max(this.layoutRevisions[frame_id]||0,response.layout_revision||0);
        if(this.layoutWrites[frame_id]===layout){delete this.layoutWrites[frame_id];this.acceptLayout(frame_id,response.layout,response.layout_revision||0);}
        this.layoutSaveError=null;
      }catch(error){
        this.layoutSaveError=error.body?.error||error.message||'Could not save frame orientation';
        if(this.layoutWrites[frame_id]===layout)delete this.layoutWrites[frame_id];
        this.failFrameAction(action,this.layoutSaveError);
      }finally{if(saveVersion===this.layoutSaveVersion){this.savingLayout=false;this.updateStatus();}}
    });
  }
  restoreLayout(){
    const layout=this.layouts?.[this.selectedFrame]||{orientation:'landscape',flipped:false};
    this.shadowRoot.querySelector('#orientation').value=layout.orientation;this.flipped=layout.flipped;
    this.shadowRoot.querySelector('.flip').setAttribute('aria-pressed',String(this.flipped));
  }
  acceptLayout(frame_id,layout,revision){
    this.layoutRevisions=this.layoutRevisions||{};
    if(revision<(this.layoutRevisions[frame_id]||0))return;
    this.layoutRevisions[frame_id]=revision;this.layouts=this.layouts||{};this.layouts[frame_id]={...layout};
    if(frame_id===this.selectedFrame)this.restoreLayout();
  }
  async syncLayout(frame_id){
    // A card can remain open while a service or another browser saves layout.
    // Do not rely on a delayed hass setter or the frame list cached at startup.
    const response=await this._hass.callApi('GET','switchbot_frame_control/frames');
    const frame=response.frames?.find(f=>f.id===frame_id);
    if(!frame)throw new Error('Destination frame is no longer configured. Reload this dashboard.');
    this.acceptLayout(frame_id,frame.layout,frame.layout_revision||0);
    return {...this.layouts[frame_id]};
  }
  targetFrame(){
    if(!this.frames?.some(f=>f.id===this.selectedFrame))throw new Error('Choose a configured destination frame first.');
    return this.selectedFrame;
  }
  setFrameControlsBusy(busy){
    for(const element of this.shadowRoot.querySelectorAll('.gallery-items button,.gallery-save,.gallery-refresh'))element.disabled=busy;
    for(const selector of ['#frame','#orientation','.flip','input','.generate','.repair','.show-baby','.restore-normal','.mode-local','.mode-hybrid','.mode-wifi'])this.shadowRoot.querySelector(selector).disabled=busy;
  }
  async loadFrames(){
    this.loadingFrames=true;const status=this.shadowRoot.querySelector('.frame-result');
    try{
      const response=await this._hass.callApi('GET','switchbot_frame_control/frames');
      if(!Array.isArray(response.frames)||!response.frames.length)throw new Error('No frames are configured.');
      this.frames=response.frames;
      this.layouts={};this.layoutRevisions={};
      for(const frame of this.frames)this.acceptLayout(frame.id,frame.layout||{orientation:'landscape',flipped:false},frame.layout_revision||0);
      const select=this.shadowRoot.querySelector('#frame');select.replaceChildren();
      for(const frame of this.frames){const option=document.createElement('option');option.value=frame.id;option.textContent=frame.name;select.append(option);}
      const wanted=this.config.frame_id||this.selectedFrame||this.frames[0].id;
      if(!this.frames.some(f=>f.id===wanted)){this.frames=null;throw new Error('The frame configured for this card was not found.');}
      this.selectedFrame=wanted;select.value=wanted;this.restoreLayout();select.disabled=false;status.textContent='';this.updateStatus();
    }catch(error){this.framesFailed=true;status.textContent=error.body?.error||error.message||'Could not load frames. Refresh this dashboard to retry.';}
    finally{this.loadingFrames=false;}
  }
  async setMode(mode){
    const action=this.beginFrameAction(this.selectedFrame,'Change connection mode');
    const status=this.shadowRoot.querySelector('.frame-result');this.setFrameControlsBusy(true);
    try{const frame_id=this.targetFrame();await this._hass.callService('switchbot_frame_control','set_connection_mode',{frame_id,mode});status.textContent='Connection mode saved for this frame.';}
    catch(error){this.failFrameAction(action,error.body?.error||error.message||'Could not change connection mode.');status.textContent='';}
    finally{this.setFrameControlsBusy(false);this.updateStatus();}
  }
  async toggleNotification(){
    const frame=this.frames?.find(f=>f.id===this.selectedFrame);if(!frame?.waterfall_entity)return;
    const action=this.beginFrameAction(frame.id,'Toggle notification');
    const status=this.shadowRoot.querySelector('.frame-result');this.setFrameControlsBusy(true);
    try{await this._hass.callService('homeassistant','toggle',{entity_id:frame.waterfall_entity});status.textContent='Selected frame’s notification switch updated.';}
    catch(error){this.failFrameAction(action,error.message||'Could not update the notification switch.');status.textContent='';}
    finally{this.setFrameControlsBusy(false);}
  }
  async notification(service){
    const action=this.beginFrameAction(this.selectedFrame,service==='show_baby'?'Show baby picture':'Restore normal slideshow');
    const status=this.shadowRoot.querySelector('.frame-result');this.setFrameControlsBusy(true);
    try{const frame_id=this.targetFrame();this.shadowRoot.querySelector('.send').disabled=true;status.textContent='Updating the selected frame…';await this._hass.callService('switchbot_frame_control',service,{frame_id});status.textContent='Selected frame updated.';}
    catch(error){this.failFrameAction(action,error.message||'Could not update the selected frame.');status.textContent='';}
    finally{this.setFrameControlsBusy(false);this.refreshPreview();}
  }
  updateStatus(){
    if(!this.shadowRoot||!this._hass)return;
    this.observeFrameActions();
    const frame=this.frames?.find(f=>f.id===this.selectedFrame);
    this.shadowRoot.querySelector('.notification-controls').hidden=!frame;
    this.shadowRoot.querySelector('.show-baby').hidden=!frame?.notification_configured;
    const bin=this._hass.states?.['sensor.frame_bin_reminder_'+this.selectedFrame];
    this.shadowRoot.querySelector('.bin-controls').hidden=!bin;
    const binToggle=this.shadowRoot.querySelector('.bin-toggle');
    binToggle.textContent=bin?.attributes.enabled?'Disable bin reminders':'Enable bin reminders';
    binToggle.setAttribute('aria-pressed',String(!!bin?.attributes.enabled));
    this.shadowRoot.querySelector('.bin-status').textContent=bin?(bin.attributes.error||`Reminders ${bin.attributes.enabled?'on':'off'}. ${bin.attributes.restore_pending?'The active reminder will still be restored and cleared.':''}`):'';
    const state=frame?this._hass.states[frame.status_entity]:null;
    this.shadowRoot.querySelector('.archive').hidden=!state?.attributes?.archive_available;
    const savedLayout=state?.attributes?.layout;
    const savedRevision=state?.attributes?.layout_revision||0;
    if(savedLayout&&!this.layoutWrites?.[this.selectedFrame]&&!this.savingLayout&&!this.uploadTransport&&savedRevision>(this.layoutRevisions?.[this.selectedFrame]||0)){
      this.acceptLayout(this.selectedFrame,savedLayout,savedRevision);this.refreshPreview();
    }
    const mode=state?.attributes?.connection_mode||'local';
    const labels={local:'Bluetooth only',hybrid:'Prefer Bluetooth; Wi-Fi/cloud when needed',wifi:'Wi-Fi only — uses SwitchBot cloud'};
    this.shadowRoot.querySelector('.connection-state').textContent=frame?`${frame.model==='frame1'?'Original AI Art Frame':'AI Art Frame 2'}${frame.panel_size?' · '+frame.panel_size+' inch':''} · ${labels[mode]||mode}`:'';
    for(const value of ['local','hybrid','wifi'])this.shadowRoot.querySelector('.mode-'+value).setAttribute('aria-pressed',String(mode===value));
    this.shadowRoot.querySelector('.connection-note').textContent=frame?.model==='frame1'?'Original frame: stored pictures can be selected over Bluetooth. New pictures require Wi-Fi and SwitchBot cloud.':'Bluetooth-only mode delivers pictures locally. Wi-Fi mode sends the picture to SwitchBot cloud and needs internet access.';
    const trigger=frame?.waterfall_entity?this._hass.states[frame.waterfall_entity]:null;
    this.shadowRoot.querySelector('.notification-state').textContent=trigger?`${trigger.attributes.friendly_name||'Notification switch'}: ${trigger.state}`:'';
    this.renderSendFeedback(frame,state);
    this.shadowRoot.querySelector('.cleanup-error').textContent=state?.attributes?.library_cleanup_error?'Previous-image cleanup: '+state.attributes.library_cleanup_error:'';
    const action=this.frameActions?.get(this.selectedFrame);
    this.shadowRoot.querySelector('.status').textContent=action?.error?`${action.label}: ${action.directError?'':'Backend failure observed after this action (causality unconfirmed). '}${action.error}`:'';
    const historical=state?.attributes?.error&&!action?.backendError;
    this.shadowRoot.querySelector('.previous-operation').hidden=!historical;
    this.shadowRoot.querySelector('.previous-operation-details').textContent=historical?`Previous operation. State last updated: ${state.last_updated||'timestamp unavailable'} (not a confirmed failure time). ${state.attributes.last_action||'Action not recorded'}. ${state.attributes.error}`:'';
  }
  failureIdentity(state){
    return JSON.stringify([state?.state,state?.attributes?.error]);
  }
  beginFrameAction(frame_id,label){
    this.frameActions??=new Map();
    const frame=this.frames?.find(f=>f.id===frame_id),baseline=this._hass?.states?.[frame?.status_entity];
    const action={frame_id,label,baseline,stamp:baseline?.last_updated,identity:this.failureIdentity(baseline),sawClear:!baseline?.attributes?.error};
    this.frameActions.set(frame_id,action);return action;
  }
  failFrameAction(action,message){
    // Keep failures scoped even if the selected frame changes before a reply.
    if(this.frameActions?.get(action.frame_id)===action){action.error=message;action.directError=true;}
    this.updateStatus();
  }
  observeFrameActions(){
    for(const [id,action] of this.frameActions||[]){
      const frame=this.frames?.find(f=>f.id===id),state=this._hass.states?.[frame?.status_entity];
      const fresh=state&&state!==action.baseline&&state.last_updated&&(!action.stamp||Date.parse(state.last_updated)>Date.parse(action.stamp));
      if(!fresh)continue;
      const error=state.attributes?.error;
      if(!error){action.sawClear=true;continue;}
      // Attribute-only republishes of the old failure (layout/mode changes,
      // unrelated context updates) are not evidence of a new failed action.
      if(state.state==='error'&&(action.sawClear||this.failureIdentity(state)!==action.identity)){
        action.backendError=error;action.error=action.error||error;
      }
    }
  }
  clearSendFeedback(){
    this.sendFeedback??=new Map();this.sendFeedback.delete(this.selectedFrame);
    this.ignoredCompleted??=new Map();
    const frame=this.frames?.find(f=>f.id===this.selectedFrame);
    this.ignoredCompleted.set(this.selectedFrame,this._hass?.states?.[frame?.status_entity]?.attributes?.library_transaction?.operation_id);
    this.shadowRoot.querySelector('.result').textContent='';this.updateStatus();
  }
  beginSendFeedback(frame,transport){
    this.beginFrameAction(frame.id,'Send picture');
    this.sendFeedback??=new Map();
    const state=this._hass.states?.[frame.status_entity];
    const operation={transport,submitting:true,phase:'preparing_source',baseline:state,baselineStamp:state?.last_updated};
    this.sendFeedback.set(frame.id,operation);return operation;
  }
  sendProgressModel(frame,state){
    if(!frame)return {kind:'idle'};
    let op=this.sendFeedback?.get(frame.id);const tx=state?.attributes?.library_transaction;
    const fresh=op&&state!==op.baseline&&(state?.last_updated!==op.baselineStamp||!op.baselineStamp);
    if(op&&!op.submitting&&(op.verified||op.observedComplete)&&fresh){
      if(state?.state==='uploading')return {kind:'pending',label:'A new image operation is starting; waiting for its identity'};
      if(tx?.operation_id!==op.id&&['prepared','registering','registered','awaiting_delivery'].includes(tx?.stage)){
        this.sendFeedback.delete(frame.id);op=null;
      }
    }
    if(this.sourcePreparation?.frame===frame.id)return {kind:'pending',label:'Preparing selected picture; delivery not started'};
    if(op?.submitting)return {kind:'pending',label:op.phase==='submitting'?'Submitting picture; waiting for delivery acknowledgement':'Preparing picture for delivery'};
    if(op?.error)return {kind:'error',error:op.error};
    if(op?.verified)return {kind:'complete',label:'Current picture verified stored and selected; physical display not inspected'};
    if(op){
      // Bluetooth/non-library replies lack a server fingerprint. Only the exact
      // request's verified reply can complete them, never generic old HA state.
      if(op.serverBound===false||!op.id||tx?.operation_id!==op.id||!fresh)return {kind:'pending',label:'Waiting for this operation to be verified; progress percentage unknown'};
    }
    if(!tx?.operation_id)return {kind:'idle'};
    if(['uploading','delivery_pending'].includes(state?.state)&&tx.stage==='complete')return {kind:'pending',label:'Waiting for the new operation identity; delivery not verified'};
    if(['delivery_error','delivery_exhausted'].includes(tx.stage))return {kind:'error',error:(tx.error||'Delivery stopped')+'. Do not upload a duplicate; inspect the existing operation.'};
    if(['complete','confirmed','device_release','device_absent','cloud_delete','cloud_sync','awaiting_absence'].includes(tx.stage)&&Number.isInteger(tx.new_index)){
      if(!op&&this.ignoredCompleted?.get(frame.id)===tx.operation_id)return {kind:'idle'};
      if(op)op.observedComplete=true;
      return {kind:'complete',label:'Current operation verified stored and selected; physical display not inspected'};
    }
    const labels={source_saved:'Exact source saved',preparing_source:'Preparing saved picture',ready:'Delivery queued',registering:'Registering picture in cloud',wake_settling:'Waking frame and allowing it to settle',waiting_storage:'Waiting for device storage',waiting_selection:'Waiting for device selection'};
    const d=tx.delivery||{};
    return {kind:'pending',label:(labels[d.phase]||'Delivery pending')+`; download attempts ${d.download_attempts||0}, selection attempts ${d.selection_attempts||0}; percentage unknown`};
  }
  renderSendFeedback(frame,state){
    const model=this.sendProgressModel(frame,state),bar=this.shadowRoot.querySelector('.send-progress');
    this.shadowRoot.querySelector('.send-progress-wrap').hidden=!['pending','complete'].includes(model.kind);
    const complete=model.kind==='complete';
    bar.dataset.complete=String(complete);bar.setAttribute('aria-label','Image delivery'+(frame?.name?' — '+frame.name:''));
    bar.setAttribute('aria-valuetext',model.label||'Delivery not active');
    if(complete)bar.setAttribute('aria-valuenow','100');else bar.removeAttribute('aria-valuenow');
    this.shadowRoot.querySelector('.send-check').hidden=!complete;
    this.shadowRoot.querySelector('.progress-sr').textContent=model.label||'';
    this.shadowRoot.querySelector('.send-error').textContent=model.kind==='error'?model.error:'';
  }
  async sourceFingerprint(encoded){
    const bytes=Uint8Array.from(atob(encoded),c=>c.charCodeAt(0));
    if(globalThis.crypto?.subtle){
      const digest=await globalThis.crypto.subtle.digest('SHA-256',bytes);
      return Array.from(new Uint8Array(digest),b=>b.toString(16).padStart(2,'0')).join('');
    }
    // SHA-256 fallback for non-secure LAN contexts without Web Crypto. The
    // fingerprint remains local except for comparison with the controller ID.
    const k=[0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];
    const h=[0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19];
    const padded=new Uint8Array(Math.ceil((bytes.length+9)/64)*64);padded.set(bytes);padded[bytes.length]=128;
    const view=new DataView(padded.buffer);view.setUint32(padded.length-8,Math.floor(bytes.length/0x20000000));view.setUint32(padded.length-4,(bytes.length*8)>>>0);
    const rotate=(x,n)=>(x>>>n)|(x<<(32-n)),w=new Uint32Array(64);
    for(let offset=0;offset<padded.length;offset+=64){
      for(let i=0;i<16;i++)w[i]=view.getUint32(offset+4*i);
      for(let i=16;i<64;i++){const x=w[i-15],y=w[i-2];w[i]=(rotate(x,7)^rotate(x,18)^(x>>>3))+w[i-16]+(rotate(y,17)^rotate(y,19)^(y>>>10))+w[i-7];}
      let [a,b,c,d,e,f,g,z]=h;
      for(let i=0;i<64;i++){const t1=(z+(rotate(e,6)^rotate(e,11)^rotate(e,25))+((e&f)^(~e&g))+k[i]+w[i])>>>0,t2=((rotate(a,2)^rotate(a,13)^rotate(a,22))+((a&b)^(a&c)^(b&c)))>>>0;z=g;g=f;f=e;e=(d+t1)>>>0;d=c;c=b;b=a;a=(t1+t2)>>>0;}
      [a,b,c,d,e,f,g,z].forEach((v,i)=>h[i]=(h[i]+v)>>>0);
    }
    return h.map(v=>v.toString(16).padStart(8,'0')).join('');
  }
  async downloadArchive(){
    const action=this.beginFrameAction(this.selectedFrame,'Download backup');
    const status=this.shadowRoot.querySelector('.repair-result');
    try{
      const backup=await this._hass.callApi('POST','switchbot_frame_control/archive',{frame_id:this.targetFrame()});
      if(this.backupURL)URL.revokeObjectURL(this.backupURL);
      const raw=atob(backup.image),bytes=Uint8Array.from(raw,c=>c.charCodeAt(0));
      this.backupURL=URL.createObjectURL(new Blob([bytes],{type:'image/jpeg'}));
      const link=this.shadowRoot.querySelector('.save-backup');link.href=this.backupURL;link.download=backup.filename;
      this.shadowRoot.querySelector('.backup-download').hidden=false;
      status.textContent='Private backup is ready. Press Save backup JPEG below.';
    }catch(error){this.failFrameAction(action,error.body?.error||error.message||'Could not download the backup.');status.textContent='';}
  }
  async repair(){
    const action=this.beginFrameAction(this.selectedFrame,'Reconnect');
    const button=this.shadowRoot.querySelector('.repair'),status=this.shadowRoot.querySelector('.repair-result');
    this.setFrameControlsBusy(true);status.textContent='Refreshing the connection and checking the frame…';
    try{const frame_id=this.targetFrame();await this._hass.callService('switchbot_frame_control','repair_connection',{frame_id});status.textContent='Connection checked. See the controller status above.';}
    catch(error){this.failFrameAction(action,error.message||'Could not reconnect. Check the frame is paired in SwitchBot and within Bluetooth range.');status.textContent='';}
    finally{this.setFrameControlsBusy(false);}
  }
  async generate(){
    const prompt=this.shadowRoot.querySelector('textarea').value.trim();
    const button=this.shadowRoot.querySelector('.generate'),send=this.shadowRoot.querySelector('.send');
    const status=this.shadowRoot.querySelector('.generation');
    if(!prompt){status.textContent='Describe the picture you want first.';return;}
    this.clearSendFeedback();button.disabled=true;button.textContent='Creating picture…';button.setAttribute('aria-busy','true');send.disabled=true;this.generatedData=null;
    const started=Date.now();status.textContent='Creating your picture… This can take up to two minutes.';
    const progress=setInterval(()=>{status.textContent=`Creating your picture… ${Math.floor((Date.now()-started)/1000)} seconds elapsed. Waiting for the image generator.`;},1000);
    try{
      const response=await this._hass.callApi('POST','switchbot_frame_control/generate',{prompt});
      this.generatedData=response.image;this.preparedSource=false;
      this.shadowRoot.querySelector('input').value='';
      this.sourceURL='data:image/jpeg;base64,'+response.image;await this.refreshPreview();send.disabled=false;
      status.textContent='Your picture is ready. Send it to the frame, or change the description and generate another.';
    }catch(error){status.textContent=error.body?.error||error.body?.message||error.message||'Could not generate the picture.';}
    finally{clearInterval(progress);button.disabled=false;button.textContent='Generate picture';button.removeAttribute('aria-busy');}
  }
  async send(confirmed=false,replaceIndex=null){
    if(this.uploadTransport)return;
    const file=this.shadowRoot.querySelector('input').files[0];
    if(!file&&!this.generatedData){this.clearSendFeedback();this.shadowRoot.querySelector('.result').textContent='Choose a picture or generate one before sending.';return;}
    const result=this.shadowRoot.querySelector('.result'),button=this.shadowRoot.querySelector('.send');
    this.shadowRoot.querySelector('.replace-confirm').hidden=true;
    const destination=this.frames?.find(f=>f.id===this.selectedFrame);
    if(!destination){result.textContent='Choose a configured destination frame first.';return;}
    const frameState=this._hass.states?.[destination.status_entity];
    const mode=frameState?.attributes?.connection_mode||'local';
    const wifi=mode==='wifi'||destination.model==='frame1';
    const override=frameState?.attributes?.baby_notification_active===true;
    if(override&&confirmed!==true){this.pendingReplaceIndex=replaceIndex;this.shadowRoot.querySelector('.override-confirm').hidden=false;return;}
    const operation=this.beginSendFeedback(destination,wifi?'wifi':'bluetooth');this.uploadTransport=operation.transport;this.updateStatus();
    button.disabled=true;this.setFrameControlsBusy(true);this.shadowRoot.querySelector('#orientation').disabled=true;this.shadowRoot.querySelector('.flip').disabled=true;this.shadowRoot.querySelector('input').disabled=true;this.shadowRoot.querySelector('.generate').disabled=true;result.textContent='';
    try{
      await this.pendingLayoutSave;
      if(this.layoutSaveError)throw new Error(this.layoutSaveError);
      const layout=await this.syncLayout(destination.id),source=this.sourceURL;
      if(this.selectedFrame!==destination.id)throw new Error('Destination changed while preparing the picture; send again.');
      const prepared=await this.preparePicture();
      if(this.sourceURL!==source||this.selectedFrame!==destination.id)throw new Error('Picture or destination changed while preparing; send again.');
      const data=prepared.transport.toDataURL('image/jpeg',0.92).split(',')[1];
      operation.fingerprint=await this.sourceFingerprint(data);operation.id=operation.fingerprint;
      prepared.transport.width=prepared.transport.height=0;prepared.preview.width=prepared.preview.height=0;
      operation.phase='submitting';this.updateStatus();
      const response=await this._hass.callApi('POST','switchbot_frame_control/upload',{image:data,layout,override_baby:override,frame_id:destination.id,...(replaceIndex!==null?{replace_index:replaceIndex}:{})});
      operation.serverBound=!!response.delivery?.operation_id;operation.verified=response.local_storage_verified===true;
      if(operation.serverBound&&response.delivery.operation_id!==operation.fingerprint){operation.verified=false;throw new Error('Controller operation identity did not match this picture. Inspect delivery before retrying.');}
      if(response.delivery&&['delivery_error','delivery_exhausted'].includes(response.delivery.stage))operation.error=response.delivery.error||'Delivery stopped; inspect the existing operation.';
      else if(!operation.verified&&!response.pending&&!response.accepted)operation.error='Delivery was not confirmed. Inspect the controller before sending again.';
    }catch(error){
      operation.error=error.body?.error||error.message||'Could not send the picture. Check the controller status before retrying.';
      const candidate=error.body?.replacement;
      if(candidate&&Number.isInteger(candidate.index)){
        this.replacement={...candidate,frame:destination.id,source:this.sourceURL,orientation:this.shadowRoot.querySelector('#orientation').value,flipped:!!this.flipped};
        const date=new Date(candidate.created_at).toLocaleDateString();
        this.shadowRoot.querySelector('.replace-details').textContent=`${destination.name} is full. Replace its oldest stored artwork (picture ${candidate.index}, added ${date}) with this picture? The old picture will leave the frame. If its cloud slot must also be freed, a private backup will be saved in Home Assistant; use Download last replaced picture to recover it. The baby notification picture is protected.`;
        this.shadowRoot.querySelector('.replace-confirm').hidden=false;
      }
    }
    finally{operation.submitting=false;this.uploadTransport=null;this.updateStatus();button.disabled=false;this.setFrameControlsBusy(false);this.shadowRoot.querySelector('#orientation').disabled=false;this.shadowRoot.querySelector('.flip').disabled=false;this.shadowRoot.querySelector('input').disabled=false;this.shadowRoot.querySelector('.generate').disabled=false;}
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
    // Mounting calibration belongs only to transport, never to the photo preview.
    if(this.flipped&&!previewOnly){ctx.translate(canvas.width,canvas.height);ctx.rotate(Math.PI);}
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
    }catch(error){if(version===this.previewVersion)this.shadowRoot.querySelector('.result').textContent='Could not read this picture. Please choose another image.';}
  }
  disconnectedCallback(){if(this.backupURL)URL.revokeObjectURL(this.backupURL);this.releaseDecodedSource();if(this.previewURL)URL.revokeObjectURL(this.previewURL);}
}
customElements.define('frame-upload-card',FrameUploadCard);
window.customCards=window.customCards||[];
window.customCards.push({type:'frame-upload-card',name:'Frame picture upload',description:'Art Frame 1 and 2: Bluetooth controls and optional Wi-Fi/cloud delivery.'});
