const state = {language:"en-US", languages:{}, drafts:{}, working:false, projectId:null, revision:null};
const $ = id => document.getElementById(id);

function persistSession() {
  try {
    localStorage.setItem("video-course-studio-session",JSON.stringify({
      projectId:state.projectId,revision:state.revision,courseName:$("course-name").value,
      language:state.language
    }));
  } catch(_) {}
}

async function api(path, data) {
  const response = await fetch(path, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "The request failed.");
  return result;
}

function sceneData(card) {
  return {
    chapter:card.closest(".chapter-card").querySelector(".chapter-title").value.trim(),
    chapter_start:card===card.closest(".chapter-card").querySelector(".scene-card"),
    heading:card.querySelector(".heading").value.trim(),
    narration:card.querySelector(".narration").value.trim(),
    points:card.querySelector(".points").value.split("\n").map(x=>x.trim()).filter(Boolean),
    asset:card.dataset.asset || "",
    visual_type:card.querySelector(".visual-type").value,
    production_note:card.querySelector(".production-note").value.trim()
  };
}

function saveDraft(markUnsaved=true) {
  state.drafts[state.language] = {
    title:$("project-title").value,
    voice:$("voice").value,
    scenes:[...document.querySelectorAll(".scene-card")].map(sceneData),
    reviewed:$("reviewed").checked
  };
  try { localStorage.setItem("video-course-studio-drafts", JSON.stringify(state.drafts)); } catch(_) {}
  persistSession();
  refreshLanguageBadges();
  if(markUnsaved)$("save-state").textContent="Unsaved changes · use Save course to keep this project on disk.";
}

function invalidateReview() {
  $("reviewed").checked=false;
  saveDraft();
}

function refreshLanguageBadges() {
  for(const card of document.querySelectorAll(".language-card")) {
    let badge=card.querySelector(".review-badge");
    if(!badge){badge=document.createElement("span");badge.className="review-badge";card.append(badge);}
    badge.textContent=state.drafts[card.dataset.code]?.reviewed?"Ready to render":"Needs review";
  }
}

function addChapter(title="", withScene=true) {
  if(document.querySelectorAll(".chapter-card").length>=24)return null;
  const chapter=document.createElement("section");
  chapter.className="chapter-card";
  chapter.innerHTML=`<div class="chapter-top">
    <span class="chapter-number"></span>
    <label class="field"><span>Chapter title</span><input class="chapter-title" maxlength="90" placeholder="Name this chapter"></label>
    <button class="secondary chapter-add-scene" type="button">+ Add scene</button>
    <button class="delete-chapter" type="button">Remove chapter</button>
  </div><div class="chapter-scenes"></div>`;
  chapter.querySelector(".chapter-title").value=title || `Chapter ${document.querySelectorAll(".chapter-card").length+1}`;
  chapter.querySelector(".chapter-title").addEventListener("input",invalidateReview);
  chapter.querySelector(".chapter-add-scene").addEventListener("click",()=>{addScene({},chapter);invalidateReview();});
  chapter.querySelector(".delete-chapter").addEventListener("click",()=>{
    if(!window.confirm("Remove this chapter and all of its scenes?"))return;
    chapter.remove();renumber();invalidateReview();
  });
  $("chapters").append(chapter);
  if(withScene)addScene({},chapter);
  renumber();
  return chapter;
}

function addScene(data={heading:"",narration:"",points:[],asset:"",visual_type:"diagram",production_note:""}, chapter=null) {
  chapter ||= document.querySelector(".chapter-card") || addChapter("",false);
  if(document.querySelectorAll(".scene-card").length>=120)return;
  const card = document.createElement("article");
  card.className = "scene-card";
  card.dataset.asset = data.asset || "";
  card.innerHTML = `<div class="scene-top"><span class="scene-number"></span><button class="delete-scene" type="button">Remove scene</button></div>
    <div class="scene-grid">
      <label class="field"><span>Scene heading</span><input class="heading" maxlength="90" placeholder="What should viewers see?"></label>
      <label class="field"><span>Visual template</span><select class="visual-type"><option value="diagram">Concept diagram</option><option value="flow">Process flow</option><option value="checklist">Checklist</option><option value="comparison">Before / after</option><option value="photo">Photo / uploaded image</option></select></label>
      <label class="field wide"><span>Visual points · one per line, up to 5</span><textarea class="points" rows="5" placeholder="A key point per line"></textarea></label>
      <label class="field wide"><span>Visual production note · for the storyboard, not displayed in the video</span><textarea class="production-note" rows="2" maxlength="300" placeholder="Example: Show a cursor-led website review"></textarea></label>
      <label class="field wide"><span>Exact narration for this language</span><textarea class="narration" rows="4" maxlength="1200" placeholder="Write the words the narrator should speak"></textarea></label>
    </div>
    <div class="scene-actions"><button type="button" class="ghost preview-voice">▶ Preview voice</button><label class="image-label">Add image<input class="image-file" type="file" accept="image/png,image/jpeg,image/webp"></label><span class="image-name"></span><audio class="voice-player" controls hidden></audio></div>`;
  card.querySelector(".heading").value=data.heading || "";
  card.querySelector(".narration").value=data.narration || "";
  card.querySelector(".points").value=(data.points || []).join("\n");
  card.querySelector(".production-note").value=data.production_note || "";
  card.querySelector(".visual-type").value=data.visual_type || "diagram";
  if(data.asset) card.querySelector(".image-name").textContent="Image attached";
  card.querySelector(".delete-scene").addEventListener("click",()=>{card.remove(); renumber(); invalidateReview();});
  card.querySelectorAll("input,textarea,select").forEach(el=>el.addEventListener("input",invalidateReview));
  card.querySelector(".preview-voice").addEventListener("click",()=>previewVoice(card));
  card.querySelector(".image-file").addEventListener("change",event=>uploadImage(card,event.target.files[0]));
  chapter.querySelector(".chapter-scenes").append(card);
  renumber();
}

function renumber() {
  const cards=[...document.querySelectorAll(".scene-card")];
  const chapters=[...document.querySelectorAll(".chapter-card")];
  cards.forEach((card,i)=>card.querySelector(".scene-number").textContent=`SCENE ${String(i+1).padStart(2,"0")}`);
  chapters.forEach((chapter,i)=>{
    chapter.querySelector(".chapter-number").textContent=`CHAPTER ${String(i+1).padStart(2,"0")}`;
    chapter.querySelector(".delete-chapter").disabled=chapters.length<=1;
    chapter.querySelector(".chapter-add-scene").disabled=cards.length>=120;
    for(const card of chapter.querySelectorAll(".scene-card"))card.querySelector(".delete-scene").disabled=chapter.querySelectorAll(".scene-card").length<=1;
  });
  $("chapter-count").textContent=`${chapters.length} chapter${chapters.length===1?"":"s"}`;
  $("scene-count").textContent=`${cards.length} scene${cards.length===1?"":"s"}`;
  $("add-chapter").disabled=chapters.length>=24||cards.length>=120;
}

function blankLanguageDraft(code) {
  const source=Object.values(state.drafts).find(draft=>draft.scenes?.length);
  if(!source)return starterDraft(code);
  return {
    title:$("course-name").value.trim()||source.title,
    voice:state.languages[code].voices[0].id,
    reviewed:false,
    scenes:source.scenes.map(scene=>({
      chapter:scene.chapter,chapter_start:scene.chapter_start,heading:scene.heading,
      narration:"",points:[],asset:"",visual_type:scene.visual_type,
      production_note:"Structure copied from another language. Rewrite the heading, visuals and narration for this audience."
    }))
  };
}

function starterDraft(code) {
  return {title:"New Course",voice:state.languages[code].voices[0].id,reviewed:false,
    scenes:[{chapter:"Chapter 1",chapter_start:true,heading:"",narration:"",
      points:[],asset:"",visual_type:"diagram",production_note:""}]};
}

function selectLanguage(code) {
  if(code===state.language && document.querySelector(".scene-card")) return;
  if(document.querySelector(".scene-card")) saveDraft();
  state.language=code;
  const draft=state.drafts[code] || (state.projectId?blankLanguageDraft(code):starterDraft(code));
  $("project-title").value=draft.title;
  $("voice").innerHTML="";
  for(const voice of state.languages[code].voices) {
    const option=document.createElement("option"); option.value=voice.id; option.textContent=voice.label; $("voice").append(option);
  }
  if(draft.voice) $("voice").value=draft.voice;
  $("chapters").innerHTML="";
  let chapter=null;
  for(const scene of draft.scenes){
    const title=scene.chapter||"Chapter 1";
    if(!chapter||scene.chapter_start===true||chapter.querySelector(".chapter-title").value!==title)chapter=addChapter(title,false);
    addScene(scene,chapter);
  }
  if(!chapter)addChapter("Chapter 1");
  $("reviewed").checked=draft.reviewed===true;
  document.querySelectorAll(".language-card").forEach(card=>card.classList.toggle("active",card.dataset.code===code));
  saveDraft(false);
}

function showStatus(title, message, error=false) {
  const result=$("result"); result.hidden=false; result.className="result"+(error?" error":"");
  result.innerHTML="";
  const h=document.createElement("h3");h.textContent=title;
  const p=document.createElement("p");p.textContent=message;
  result.append(h,p);
  result.scrollIntoView({behavior:"smooth",block:"nearest"});
}

async function previewVoice(card) {
  const button=card.querySelector(".preview-voice");
  const text=card.querySelector(".narration").value.trim().slice(0,300);
  if(!text){showStatus("Add narration first","Write the text that this narrator should speak.",true);return;}
  button.disabled=true;button.textContent="Generating voice…";
  try {
    const result=await api("/api/voice",{language:state.language,voice:$("voice").value,text});
    const player=card.querySelector(".voice-player");player.src=result.audio;player.hidden=false;await player.play();
  } catch(error) {showStatus("Voice preview failed",error.message,true);}
  finally {button.disabled=false;button.textContent="▶ Preview voice";}
}

async function uploadImage(card,file) {
  if(!file) return;
  if(file.size>5_000_000){showStatus("Image too large","Use an image smaller than 5 MB.",true);return;}
  const label=card.querySelector(".image-name");label.textContent="Uploading image…";
  try {
    const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsDataURL(file);});
    const result=await api("/api/upload",{data});
    card.dataset.asset=result.asset;card.querySelector(".visual-type").value="photo";label.textContent=file.name+" attached";invalidateReview();
  } catch(error) {label.textContent="";showStatus("Image upload failed",error.message,true);}
}

async function refreshProjects() {
  const response=await fetch("/api/projects",{cache:"no-store"});
  const {projects}=await response.json();
  const select=$("saved-projects");select.innerHTML="";
  const empty=document.createElement("option");empty.value="";empty.textContent="New course";select.append(empty);
  for(const project of projects){const option=document.createElement("option");option.value=project.id;option.textContent=project.name+" · "+project.reviewed_languages.length+" ready";select.append(option);}
  select.value=state.projectId||"";
}

async function refreshRenders() {
  const response=await fetch("/api/renders",{cache:"no-store"});
  if(!response.ok)return;
  const {renders}=await response.json();
  const container=$("render-history");container.innerHTML="";
  if(!renders.length){const empty=document.createElement("p");empty.className="muted";empty.textContent="No language batches rendered yet.";container.append(empty);return;}
  for(const render of renders){
    const row=document.createElement("div");row.className="render-history-row";
    const details=document.createElement("div");
    const title=document.createElement("strong");title.textContent=render.course_name;
    const meta=document.createElement("span");meta.className="muted";
    meta.textContent=`${render.languages.join(", ")} · ${render.state} · ${new Date(render.updated_at).toLocaleString()}`;
    details.append(title,meta);row.append(details);
    if(render.viewer){
      const link=document.createElement("a");link.href=render.viewer;link.textContent="Open language chooser →";row.append(link);
    }
    container.append(row);
  }
}

async function saveCourse(quiet=false) {
  saveDraft();
  const versions={};
  for(const [code,draft] of Object.entries(state.drafts)) if(state.languages[code]) versions[code]=draft;
  const body={name:$("course-name").value.trim(),versions};
  if(state.projectId){body.id=state.projectId;body.revision=state.revision;}
  const {project}=await api("/api/projects",body);
  state.projectId=project.id;state.revision=project.revision;state.drafts=project.versions;
  persistSession();
  $("save-state").textContent=`Saved on this computer · revision ${project.revision}`;
  await refreshProjects();
  if(!quiet)showStatus("Course saved",`Your course and ${Object.keys(project.versions).length} language draft(s) are saved on this computer.`);
  return project;
}

async function loadCourse(id) {
  if(!id)return;
  const response=await fetch(`/api/projects/${id}`,{cache:"no-store"});
  if(!response.ok)throw new Error("Saved course could not be loaded.");
  const project=await response.json();
  state.projectId=project.id;state.revision=project.revision;state.drafts=project.versions;
  $("course-name").value=project.name;
  $("chapters").innerHTML="";
  const target=project.versions[state.language]?state.language:Object.keys(project.versions)[0];
  state.language="";
  selectLanguage(target);
  $("save-state").textContent=`Loaded from disk · revision ${project.revision}`;
  $("saved-projects").value=project.id;
}

function newCourse() {
  if(!window.confirm("Start a new course? Unsaved changes in the current editor will be replaced."))return;
  state.projectId=null;state.revision=null;state.drafts={};
  $("course-name").value="New Course";$("chapters").innerHTML="";state.language="";
  selectLanguage("en-US");$("saved-projects").value="";
  $("save-state").textContent="New course · not saved on disk yet.";
}

async function createTopicCourse(event) {
  event.preventDefault();
  const status=$("topic-status");
  const sections=$("topic-sections").value.split(/\r?\n/).map(x=>x.trim()).filter(Boolean);
  if(sections.length>8){status.textContent="Use up to eight lesson sections.";return;}
  if($("save-state").textContent.startsWith("Unsaved changes") &&
     !window.confirm("This editor has unsaved changes. Create a new saved course and switch to it?"))return;
  const button=$("topic-form").querySelector('button[type="submit"]');
  button.disabled=true;status.textContent="Creating a saved storyboard…";
  try {
    const {project}=await api("/api/course-outline",{
      topic:$("topic-name").value.trim(),audience:$("topic-audience").value.trim(),
      goal:$("topic-goal").value.trim(),language:$("topic-language").value,sections
    });
    await loadCourse(project.id);
    await refreshProjects();
    const draft=project.versions[$("topic-language").value];
    const chapters=draft.scenes.filter(scene=>scene.chapter_start).length;
    status.textContent=`Saved ${chapters} chapters and ${draft.scenes.length} scenes. Add accurate narration, examples and visuals before you review and render.`;
    document.querySelector(".scenes-workspace").scrollIntoView({behavior:"smooth",block:"start"});
  } catch(error){status.textContent=`Could not create course: ${error.message}`;}
  finally {button.disabled=false;}
}

function setWorking(working) {
  state.working=working;
  $("render").disabled=working;$("render-all").disabled=working;
  $("render").textContent=working?"Rendering…":"Render this language →";
}

function addDownload(parent,label,url,filename) {
  const link=document.createElement("a");link.href=url;link.download=filename;link.textContent=label;parent.append(link);
}

function displayCompleted(status, singleLanguage) {
  localStorage.removeItem("video-course-studio-active-job");
  setWorking(false);
  refreshRenders().catch(()=>{});
  if(status.kind==="batch"){
    const codes=Object.keys(status.results);
    showStatus("Language videos are ready",`${codes.length} separate videos completed for ${status.course_name}.`);
    const result=$("result");
    const viewer=document.createElement("a");viewer.className="primary";viewer.href=status.viewer;viewer.textContent="Open language chooser →";result.append(viewer);
    const list=document.createElement("div");list.className="language-results";
    for(const code of codes){
      const item=status.results[code];const block=document.createElement("div");block.className="language-result-item";
      const name=document.createElement("strong");name.textContent=state.languages[code]?.label||code;
      const links=document.createElement("div");links.className="download-row";
      addDownload(links,"MP4",item.video,`Course_${code}.mp4`);
      addDownload(links,"Subtitles",item.subtitles,`Course_${code}.srt`);
      block.append(name,links);list.append(block);
    }
    result.append(list);
  } else {
    showStatus("Your video is ready",`${status.seconds} seconds · ${state.languages[singleLanguage]?.label||singleLanguage}`);
    const result=$("result");
    const video=document.createElement("video");video.controls=true;video.preload="metadata";video.src=status.video;
    const links=document.createElement("div");links.className="download-row";
    addDownload(links,"Download MP4",status.video,`Course_${singleLanguage}.mp4`);
    addDownload(links,"Download subtitles",status.subtitles,`Course_${singleLanguage}.srt`);
    result.append(video,links);
  }
}

async function pollJob(jobId,singleLanguage) {
  const response=await fetch(`/api/jobs/${jobId}`,{cache:"no-store"});
  if(!response.ok)throw new Error("Render job could not be found.");
  const status=await response.json();
  if(status.state==="complete"){displayCompleted(status,singleLanguage);return;}
  if(status.state==="failed"||status.state==="interrupted")throw new Error(status.message);
  const result=$("result");
  if(result.hidden)showStatus("Rendering your video",status.message);
  else result.querySelector("p").textContent=status.message;
  setTimeout(()=>pollJob(jobId,singleLanguage).catch(renderFailed),1500);
}

function renderFailed(error) {
  localStorage.removeItem("video-course-studio-active-job");
  setWorking(false);showStatus("Render stopped",error.message,true);
}

async function render() {
  saveDraft();
  if(!state.drafts[state.language].reviewed){showStatus("Review this language first","Check the review box after confirming the script, visuals and voice choice.",true);return;}
  const project={title:$("project-title").value.trim(),language:state.language,voice:$("voice").value,scenes:[...document.querySelectorAll(".scene-card")].map(sceneData)};
  setWorking(true);
  try {
    const {job}=await api("/api/render",project);
    localStorage.setItem("video-course-studio-active-job",JSON.stringify({job,language:project.language}));
    showStatus("Rendering your video","Waiting for the renderer. This can take several minutes.");
    await pollJob(job,project.language);
  } catch(error){renderFailed(error);}
}

async function renderAll() {
  saveDraft();
  if(!Object.values(state.drafts).some(draft=>draft.reviewed)){showStatus("No languages reviewed","Review and mark each language that should be rendered.",true);return;}
  setWorking(true);
  try {
    const project=await saveCourse(true);
    const {job}=await api("/api/render-batch",{project_id:project.id});
    refreshRenders().catch(()=>{});
    localStorage.setItem("video-course-studio-active-job",JSON.stringify({job,language:state.language}));
    showStatus("Rendering language versions","Each reviewed language will produce its own MP4 and subtitles.");
    await pollJob(job,state.language);
  } catch(error){renderFailed(error);}
}

async function start() {
  const data=await fetch("/api/languages").then(response=>response.json());state.languages=data.languages;
  let savedLanguage="";
  try {state.drafts=JSON.parse(localStorage.getItem("video-course-studio-drafts")||"{}");} catch(_) {}
  try {
    const session=JSON.parse(localStorage.getItem("video-course-studio-session")||"null");
    if(session){
      state.projectId=session.projectId||null;state.revision=session.revision||null;
      if(typeof session.courseName==="string")$("course-name").value=session.courseName;
      if(state.languages[session.language])savedLanguage=session.language;
    }
  } catch(_) {}
  for(const [code,lang] of Object.entries(state.languages)){
    const button=document.createElement("button");button.type="button";button.className="language-card";button.dataset.code=code;
    const native=document.createElement("span");native.className="native";native.textContent=lang.native;
    const label=document.createElement("small");label.textContent=lang.label;
    button.append(native,label);button.addEventListener("click",()=>selectLanguage(code));$("languages").append(button);
    const option=document.createElement("option");option.value=code;option.textContent=lang.label;$("topic-language").append(option);
  }
  $("topic-form").addEventListener("submit",createTopicCourse);
  selectLanguage(savedLanguage || Object.keys(state.drafts).find(code=>state.languages[code]) || "en-US");
  await refreshProjects();
  await refreshRenders();
  $("save-state").textContent=state.projectId
    ? `Working draft for saved course · revision ${state.revision}. Save any changes when ready.`
    : "New course · save it to keep this project on disk.";
  $("course-name").addEventListener("input",()=>{$("save-state").textContent="Unsaved changes · use Save course to keep this project on disk.";persistSession();});
  $("project-title").addEventListener("input",invalidateReview);$("voice").addEventListener("change",invalidateReview);
  $("reviewed").addEventListener("change",saveDraft);
  $("add-chapter").addEventListener("click",()=>{addChapter();invalidateReview();});
  $("save-project").addEventListener("click",()=>saveCourse().catch(error=>showStatus("Save failed",error.message,true)));
  $("saved-projects").addEventListener("change",event=>loadCourse(event.target.value).catch(error=>showStatus("Load failed",error.message,true)));
  $("new-project").addEventListener("click",newCourse);
  $("render").addEventListener("click",render);
  $("render-all").addEventListener("click",renderAll);
  try {
    const active=JSON.parse(localStorage.getItem("video-course-studio-active-job")||"null");
    if(active?.job){setWorking(true);pollJob(active.job,active.language).catch(renderFailed);}
  } catch(_) {}
}
start().catch(error=>showStatus("Studio could not start",error.message,true));
