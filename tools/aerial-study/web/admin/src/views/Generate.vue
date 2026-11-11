<template>
<div>
 <header class="topbar"><div class="crumb">题库 / <b>AI 生成</b></div><div class="search">⌕ <span>搜索素材、题目…</span></div><div class="top-actions"><router-link class="btn ghost" to="/admin/questions">返回题库</router-link><button class="btn" :disabled="generating" @click="run">开始生成</button><div class="avatar">AS</div></div></header>
 <div class="content">
  <div class="page-title"><div><h1>AI 生成题目</h1><p>选择题型与素材，AI 生成后先进入草稿，不会自动发布。</p></div></div>
  <div class="flow" style="display:grid;grid-template-columns:250px minmax(0,1fr) 300px;gap:16px;align-items:start">
   <aside class="panel" style="padding:16px">
    <div v-for="(s,i) in steps" :key="s" style="display:flex;gap:10px;padding:10px 0;color:#98a4b5;font-size:13px" :style="stepStyle(i)">
      <span style="width:24px;height:24px;border-radius:50%;background:#eef3fa;display:grid;place-items:center;font-size:11px">{{ i+1 }}</span>{{s}}
    </div>
   </aside>
   <section class="panel" style="padding:18px">
    <h2 style="font-size:15px;margin:0 0 14px">题型</h2>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:9px"><button v-for="t in tax.questionTypes" :key="t.code" class="typebtn" :class="{on:form.questionType===t.code}" @click="form.questionType=t.code">{{t.name}}</button></div>
    <div class="row" style="margin-top:16px"><label class="field grow">年龄<select v-model="form.ageGroupId"><option :value="null">未指定</option><option v-for="a in tax.ageGroups" :key="a.id" :value="a.id">{{a.name}}</option></select></label><label class="field grow">学科<select v-model="form.subjectId"><option :value="null">未指定</option><option v-for="s in tax.subjects" :key="s.id" :value="s.id">{{s.name}}</option></select></label></div>
    <h2 style="font-size:15px;margin:20px 0 10px">选择素材 <span class="faint" style="font-weight:400;font-size:12px">已选 {{ selected.length }} 张</span></h2>
    <div class="gallery" style="grid-template-columns:repeat(4,1fr)"><button v-for="m in materials" :key="m.sha256" class="mat" :class="{on:selected.includes(m.sha256)}" @click="pick(m.sha256)"><img :src="m.url"><span>{{m.title}}</span></button></div>
    <div v-if="!materials.length" class="empty">暂无素材，请先上传</div>
   </section>
   <aside class="panel" style="padding:18px;position:sticky;top:90px"><h2 style="font-size:15px;margin:0 0 10px">生成设置</h2>
    <div class="summary-row" v-for="r in summary" :key="r[0]"><span>{{r[0]}}</span><b>{{r[1]}}</b></div>
    <label class="field" style="margin-top:12px">数量<input v-model.number="form.count" type="number" min="1" max="20"></label>
    <button class="btn" style="width:100%;margin-top:14px" :disabled="generating||!canRun" @click="run">{{ generating?'生成中…':'生成草稿' }}</button>
    <div v-if="job" class="notice" style="margin-top:12px;display:block">任务 {{job.id}} · {{job.status}}<span v-if="job.error"><br>{{job.error}}</span></div>
    <div v-if="resultQuestions.length" style="margin-top:12px"><div style="font-size:12px;color:#7c8ba1;margin-bottom:6px">已生成草稿</div><div v-for="q in resultQuestions" :key="q.id" class="result-row"><img :src="q.image?.url"><div><b>{{q.answer}}</b><br><small>{{q.prompt}}</small></div></div><router-link class="btn ghost" style="width:100%;margin-top:10px" to="/admin/questions">去题库查看</router-link></div>
   </aside>
  </div>
 </div><div v-if="toast" class="toast">{{toast}}</div>
</div>
</template>
<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { api } from '../api'
const tax=ref({ageGroups:[],subjects:[],questionTypes:[]}); const materials=ref([]); const selected=ref([]); const generating=ref(false); const job=ref(null); const resultQuestions=ref([]); const toast=ref('')
const form=ref({questionType:'word_image_choice',ageGroupId:null,subjectId:null,count:2,lang:'zh'})
const steps=['选择题型','年龄与学科','选择素材','生成设置','预览草稿']
let timer=null
const selectedType=computed(()=>tax.value.questionTypes.find(t=>t.code===form.value.questionType))
const canRun=computed(()=>!selectedType.value?.requiresImage||selected.value.length>0)
const summary=computed(()=>[['题型',selectedType.value?.name||'-'],['年龄 / 学科',(tax.value.ageGroups.find(a=>a.id===form.value.ageGroupId)?.name||'未指定')+' · '+(tax.value.subjects.find(s=>s.id===form.value.subjectId)?.name||'未指定')],['素材',selected.value.length+' 张'],['数量',form.value.count+' 道']])
function stepStyle(i){return i<3?{color:'#1d4ed8'}:{}}
function pick(id){selected.value=selected.value.includes(id)?selected.value.filter(x=>x!==id):[...selected.value,id]}
async function load(){tax.value=await api('/api/v1/admin/taxonomies'); const m=await api('/api/v1/admin/materials?limit=200'); materials.value=m.items||[]}
async function run(){generating.value=true;resultQuestions.value=[];try{const d=await api('/api/v1/admin/generate',{method:'POST',body:{materialId:selected.value[0]||null,materialIds:selected.value,questionType:form.value.questionType,ageGroupId:form.value.ageGroupId,subjectId:form.value.subjectId,count:form.value.count,lang:form.value.lang}});job.value=d.job;poll()}catch(e){toast.value=e.message;generating.value=false}}
async function poll(){if(!job.value)return;try{const d=await api('/api/v1/admin/jobs/'+job.value.id);job.value=d.job;if(['succeeded','failed'].includes(job.value.status)){generating.value=false;resultQuestions.value=job.value.result?.questions||[];if(job.value.status==='failed')toast.value=job.value.error||'生成失败';return}}catch(e){}timer=setTimeout(poll,1500)}
onMounted(async()=>{try{await load()}catch(e){toast.value=e.message}});onUnmounted(()=>clearTimeout(timer))
</script>
<style scoped>.typebtn{border:1px solid #e6ecf5;border-radius:11px;padding:12px;font-size:13px;background:#fff}.typebtn.on{border-color:#9fc0ff;background:#f4f8ff;color:#1d4ed8;font-weight:600}.mat{border:2px solid transparent;border-radius:11px;background:#f8fafd;padding:7px;text-align:center}.mat.on{border-color:#2563eb;background:#f4f8ff}.mat img{width:100%;height:76px;object-fit:contain;background:#fff;border-radius:7px}.mat span{display:block;font-size:11px;margin-top:6px;color:#596b82}.summary-row{display:flex;justify-content:space-between;font-size:13px;padding:8px 0;border-bottom:1px solid #f0f4f9;color:#64748b}.summary-row b{color:#26364d}.result-row{display:flex;gap:9px;border:1px solid #dce8fb;border-radius:10px;padding:8px;background:#f8fbff;margin-bottom:7px}.result-row img{width:52px;height:43px;object-fit:contain;background:#fff;border-radius:6px}.result-row small{color:#7b8ba1}</style>
