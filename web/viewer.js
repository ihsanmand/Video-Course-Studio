const languageNames={
  "en-US":{label:"English",native:"English"},
  "ur-PK":{label:"Urdu (Pakistan)",native:"اردو"},
  "de-DE":{label:"German",native:"Deutsch"},
  "ar-SA":{label:"Arabic",native:"العربية"}
};

function link(label,url,filename){const a=document.createElement("a");a.href=url;a.download=filename;a.textContent=label;return a;}
function timeLabel(seconds){const mins=Math.floor(seconds/60);const rest=Math.floor(seconds%60);return `${mins}:${String(rest).padStart(2,"0")}`;}

function activate(code,job){
  const item=job.results[code];if(!item)return;
  const video=document.getElementById("course-video");
  video.pause();video.innerHTML="";
  const source=document.createElement("source");source.src=item.video;source.type="video/mp4";video.append(source);
  if(item.captions){const track=document.createElement("track");track.kind="subtitles";track.label=languageNames[code]?.label||code;track.srclang=code.split("-")[0];track.src=item.captions;video.append(track);}
  video.load();
  const chapters=document.getElementById("viewer-chapters");chapters.innerHTML="";
  chapters.hidden=!item.chapters?.length;
  for(const chapter of item.chapters||[]){
    const button=document.createElement("button");button.type="button";
    button.textContent=`${timeLabel(chapter.start)} · ${chapter.title}`;
    button.addEventListener("click",()=>{video.currentTime=chapter.start;video.play().catch(()=>{});});
    chapters.append(button);
  }
  document.getElementById("current-language").textContent=languageNames[code]?.label||code;
  document.getElementById("runtime").textContent=`${Math.round(item.seconds)} seconds`;
  const downloads=document.getElementById("viewer-downloads");downloads.innerHTML="";
  downloads.append(link("Download MP4",item.video,`Course_${code}.mp4`),link("Download subtitles",item.subtitles,`Course_${code}.srt`));
  document.querySelectorAll(".viewer-language").forEach(button=>button.classList.toggle("active",button.dataset.code===code));
}

async function startViewer(){
  const jobId=window.location.pathname.split("/").pop();
  const response=await fetch(`/api/jobs/${jobId}`,{cache:"no-store"});
  if(!response.ok)throw new Error("The course could not be found.");
  const job=await response.json();
  if(job.state!=="complete"||job.kind!=="batch")throw new Error("The language videos are not ready yet.");
  document.getElementById("viewer-title").textContent=job.course_name||"Choose your language";
  const container=document.getElementById("viewer-languages");
  const codes=Object.keys(job.results);
  for(const code of codes){
    const button=document.createElement("button");button.type="button";button.className="language-card viewer-language";button.dataset.code=code;
    const native=document.createElement("span");native.className="native";native.textContent=languageNames[code]?.native||code;
    const label=document.createElement("small");label.textContent=languageNames[code]?.label||code;
    button.append(native,label);button.addEventListener("click",()=>activate(code,job));container.append(button);
  }
  activate(codes[0],job);
}
startViewer().catch(error=>{document.getElementById("viewer-title").textContent="Viewer unavailable";document.getElementById("viewer-subtitle").textContent=error.message;});
