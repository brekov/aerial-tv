<template>
<div>
  <header class="topbar">
    <div class="crumb">学习管理 / <b>题库</b></div>
    <div class="search">⌕ <span>搜索题干、答案、题目 ID…</span></div>
    <div class="top-actions">
      <router-link class="btn ghost" to="/admin/generate">AI 生成</router-link>
      <button class="btn" @click="startCreate">＋ 新建题目</button>
      <div class="avatar">AS</div>
    </div>
  </header>
  <div class="content">
    <div class="page-title">
      <div><h1>题库管理</h1><p>按年龄、学科和题型组织学习内容，预览、编辑与发布题目。</p></div>
      <div class="quick-stats">
        <div class="stat"><span>全部题目</span><b>{{ total }}</b></div>
        <div class="stat"><span>已启用</span><b>{{ count('active') }}</b></div>
        <div class="stat"><span>草稿</span><b>{{ count('draft') }}</b></div>
        <div class="stat"><span>易错题</span><b>{{ wrongCount }}</b></div>
      </div>
    </div>
    <div class="notice">💡 <span><b>题库已按新结构整理。</b> 图片题现在显示缩略图和可读标题，分类不再显示内部代码。</span></div>
    <div class="body-grid">
      <aside class="filter-card">
        <div class="filter-head"><span>筛选</span><button class="link" @click="reset">重置</button></div>
        <div class="filter-group"><div class="filter-label">年龄 / 学段</div><div class="filter-list"><span class="filter-chip" :class="{on:ageGroupId===null}" @click="setAge(null)">全部</span><span v-for="a in tax.ageGroups" :key="a.id" class="filter-chip" :class="{on:ageGroupId===a.id}" @click="setAge(a.id)">{{a.name}}</span></div></div>
        <div class="filter-group"><div class="filter-label">学科</div><div class="filter-list"><span class="filter-chip" :class="{on:subjectId===null}" @click="setSubject(null)">全部</span><span v-for="s in tax.subjects" :key="s.id" class="filter-chip" :class="{on:subjectId===s.id}" @click="setSubject(s.id)">{{s.name}}</span></div></div>
        <div class="filter-group"><div class="filter-label">题型</div><div class="filter-list"><span class="filter-chip" :class="{on:!type}" @click="setType('')">全部</span><span v-for="t in tax.questionTypes" :key="t.code" class="filter-chip" :class="{on:type===t.code}" @click="setType(t.code)">{{t.name}}</span></div></div>
        <div class="filter-group"><div class="filter-label">答题方式</div><div class="filter-list"><span class="filter-chip" :class="{on:!mode}" @click="setMode('')">全部</span><span class="filter-chip" :class="{on:mode==='voice'}" @click="setMode('voice')">跟读</span><span class="filter-chip" :class="{on:mode==='choice'}" @click="setMode('choice')">选择</span></div></div>
        <div class="filter-group"><div class="filter-label">状态</div><div class="filter-list"><span class="filter-chip" :class="{on:!status}" @click="setStatus('')">全部</span><span class="filter-chip" :class="{on:status==='active'}" @click="setStatus('active')">启用</span><span class="filter-chip" :class="{on:status==='draft'}" @click="setStatus('draft')">草稿</span><span class="filter-chip" :class="{on:status==='disabled'}" @click="setStatus('disabled')">已停用</span></div></div>
      </aside>
      <section>
        <div class="list-head"><h2>全部题目</h2><span class="count">共 {{ total }} 题</span><button class="link" @click="load" style="margin-left:auto">刷新</button></div>
        <div v-if="loading" class="question-list"><div v-for="i in 4" :key="i" class="skeleton"></div></div>
        <div v-else-if="!items.length" class="panel empty"><b>没有符合条件的题目</b>试试重置筛选，或新建一道题。</div>
        <div v-else class="question-list">
          <article v-for="q in items" :key="q.id" class="q-card">
            <div class="q-thumb"><img v-if="img(q)" :src="img(q)" :alt="q.answer"><span v-else style="color:#9aabbb">无图片</span></div>
            <div class="q-main">
              <div class="q-title">{{ title(q) }}</div>
              <div class="q-answer">答案 <b>{{ cleanAnswer(q.answer) }}</b><span class="pill" :class="statusClass(q.status)">{{ statusText(q.status) }}</span></div>
              <div class="q-tags"><span class="pill blue">{{ q.ageGroup?.name || '未分类' }}</span><span class="pill">{{ q.subject?.name || '未分类' }}</span><span class="pill">{{ q.typeLabel || typeName(q.type) }}</span><span class="pill">{{ q.answerModeLabel || (q.answerMode==='choice'?'选择':'跟读') }}</span></div>
              <div class="q-note">最近更新 {{ q.updatedAt || '-' }} · 来源 {{ q.source==='ai'?'AI':'手动' }}</div>
            </div>
            <div class="q-stats"><span>错误率</span><b>{{ pct(q.stats?.wrongRate) }}</b>{{ q.stats?.attempts || 0 }} 次作答 · {{ q.stats?.wrong || 0 }} 次错误</div>
            <div class="q-actions"><button class="link" @click="preview(q)">预览</button><button class="link" @click="startEdit(q)">编辑</button><button class="link danger" @click="remove(q)">删除</button></div>
          </article>
        </div>
      </section>
    </div>
  </div>

  <div v-if="active" class="drawer-backdrop" @click.self="active=null"></div>
  <aside v-if="active==='preview'" class="drawer">
    <div class="drawer-head"><h2>题目预览</h2><button class="close" @click="active=null">×</button></div>
    <div v-if="detailLoading" class="drawer-body"><div class="skeleton" style="height:220px"></div></div>
    <template v-else-if="detail">
      <div class="drawer-body">
        <div class="preview-img"><img v-if="img(detail.question)" :src="img(detail.question)" :alt="detail.question.answer"></div>
        <div class="answer-card"><span>正确答案</span><b>{{ cleanAnswer(detail.question.answer) }}</b></div>
        <div class="meta">
          <div class="meta-item"><span>题干</span>{{ detail.question.prompt }}</div>
          <div class="meta-item"><span>题型</span>{{ detail.question.typeLabel || typeName(detail.question.type) }}</div>
          <div class="meta-item"><span>年龄 / 学科</span>{{ detail.question.ageGroup?.name || '未分类' }} · {{ detail.question.subject?.name || '未分类' }}</div>
          <div class="meta-item"><span>答题方式</span>{{ detail.question.answerModeLabel || (detail.question.answerMode==='choice'?'选择':'跟读') }}</div>
          <div class="meta-item"><span>难度</span>{{ '★'.repeat(Number(detail.question.difficulty)||1) }}{{ '☆'.repeat(Math.max(0,5-(Number(detail.question.difficulty)||1))) }}</div>
          <div class="meta-item"><span>状态</span>{{ statusText(detail.question.status) }}</div>
        </div>
        <div class="stats"><div class="stat2"><span>作答次数</span><b>{{ detail.question.stats?.attempts || 0 }}</b></div><div class="stat2"><span>错误次数</span><b>{{ detail.question.stats?.wrong || 0 }}</b></div><div class="stat2"><span>错误率</span><b>{{ pct(detail.question.stats?.wrongRate) }}</b></div></div>
        <h3 style="font-size:14px;margin:0 0 4px">最近作答</h3>
        <div v-for="a in (detail.attempts||[]).slice(0,8)" :key="a.id||a.created_at" class="attempt"><span>{{ a.created_at || a.createdAt }} · {{ a.transcript || (a.selected_option || '—') }}</span><span :class="a.correct?'ok':'bad'">{{ a.correct?'正确':'错误' }}</span></div>
        <div v-if="!(detail.attempts||[]).length" class="empty" style="padding:20px">暂无作答记录</div>
      </div>
      <div class="drawer-foot"><button class="btn ghost" @click="toggle(detail.question)">{{ detail.question.status==='active'?'停用题目':'启用题目' }}</button><button class="btn" @click="startEdit(detail.question)">编辑题目</button></div>
    </template>
  </aside>

  <aside v-if="active==='editor'" class="drawer">
    <div class="drawer-head"><h2>{{ form.id ? '编辑题目' : '新建题目' }}</h2><button class="close" @click="active=null">×</button></div>
    <div class="drawer-body">
      <div class="preview-img"><img v-if="form.imageId && selectedMaterial" :src="selectedMaterial.url" :alt="form.answer"><span v-else style="color:#9aabbb">选择素材后显示预览</span></div>
      <div class="form-grid">
        <label class="field full">题干<input v-model="form.prompt" placeholder="例如：请读出图中醒目的词语。"></label>
        <label class="field full">答案<input v-model="form.answer" placeholder="例如：bear"></label>
        <label class="field">年龄<select v-model="form.ageGroupId"><option :value="null">未分类</option><option v-for="a in tax.ageGroups" :key="a.id" :value="a.id">{{a.name}}</option></select></label>
        <label class="field">学科<select v-model="form.subjectId"><option :value="null">未分类</option><option v-for="s in tax.subjects" :key="s.id" :value="s.id">{{s.name}}</option></select></label>
        <label class="field">题型<select v-model="form.type"><option v-for="t in tax.questionTypes" :key="t.code" :value="t.code">{{t.name}}</option></select></label>
        <label class="field">答题方式<select v-model="form.answerMode"><option value="voice">跟读</option><option value="choice">选择</option></select></label>
        <label class="field">难度<select v-model.number="form.difficulty"><option v-for="i in 5" :key="i" :value="i">{{i}} 星</option></select></label>
        <label class="field">状态<select v-model="form.status"><option value="draft">草稿</option><option value="active">启用</option><option value="disabled">停用</option></select></label>
        <label class="field full">素材<select v-model="form.imageId"><option :value="null">不选择素材</option><option v-for="m in materials" :key="m.sha256" :value="m.sha256">{{ m.title }}</option></select></label>
        <label class="field full" v-if="form.answerMode==='choice'">选项（每行一个，答案必须在其中）<textarea v-model="optionsText" placeholder="bear&#10;apple&#10;lion"></textarea></label>
      </div>
    </div>
    <div class="drawer-foot"><button class="btn ghost" @click="active=null">取消</button><button class="btn" :disabled="saving" @click="save">{{ saving?'保存中…':'保存' }}</button></div>
  </aside>

  <div v-if="toast" class="toast">{{ toast }}</div>
</div>
</template>
<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import { api } from '../api'
const tax=ref({ageGroups:[],subjects:[],questionTypes:[]}); const items=ref([]); const total=ref(0); const loading=ref(false); const wrongCount=ref(0)
const ageGroupId=ref(null), subjectId=ref(null), type=ref(''), mode=ref(''), status=ref('')
const active=ref(null), detail=ref(null), detailLoading=ref(false), saving=ref(false), toast=ref('')
const materials=ref([]); const optionsText=ref('')
const form=reactive({id:null,prompt:'',answer:'',type:'word_image',ageGroupId:null,subjectId:null,answerMode:'voice',difficulty:1,status:'draft',imageId:null})
function typeName(code){return tax.value.questionTypes.find(x=>x.code===code)?.name||code}
function count(s){return items.value.filter(q=>q.status===s).length}
function pct(v){return `${Math.round((Number(v)||0)*100)}%`}
function statusText(s){return ({active:'已启用',draft:'草稿',disabled:'已停用',reviewed:'已审核'})[s]||s}
function statusClass(s){return s==='active'?'green':s==='draft'?'amber':s==='disabled'?'red':''}
function cleanAnswer(a){return (a||'').split('|')[0]}
function img(q){return q?.imageUrl||q?.image?.url||null}
function title(q){return q.displayTitle||q.prompt||`题目 #${q.id}`}
function reset(){ageGroupId.value=null;subjectId.value=null;type.value='';mode.value='';status.value=''}
function setAge(v){ageGroupId.value=v;load()} function setSubject(v){subjectId.value=v;load()} function setType(v){type.value=v;load()} function setMode(v){mode.value=v;load()} function setStatus(v){status.value=v;load()}
async function load(){
  loading.value=true
  try{ const p=new URLSearchParams({limit:'100'}); if(ageGroupId.value) p.set('ageGroupId',ageGroupId.value); if(subjectId.value) p.set('subjectId',subjectId.value); if(type.value) p.set('type',type.value); if(mode.value) p.set('answerMode',mode.value); if(status.value) p.set('status',status.value); const d=await api('/api/v1/admin/questions?'+p); items.value=d.items||[]; total.value=d.total??items.value.length; wrongCount.value=items.value.filter(q=>(q.stats?.wrong||0)>0).length }
  catch(e){toast.value=e.message} finally{loading.value=false}
}
async function loadMeta(){ tax.value=await api('/api/v1/admin/taxonomies'); const m=await api('/api/v1/admin/materials?limit=200'); materials.value=m.items||[] }
async function preview(q){ active.value='preview'; detail.value=null; detailLoading.value=true; try{detail.value=await api(`/api/v1/admin/questions/${q.id}`)}catch(e){toast.value=e.message}finally{detailLoading.value=false} }
function startCreate(){ Object.assign(form,{id:null,prompt:'',answer:'',type:'word_image',ageGroupId:null,subjectId:null,answerMode:'voice',difficulty:1,status:'draft',imageId:null}); optionsText.value=''; active.value='editor' }
function startEdit(q){ Object.assign(form,{id:q.id,prompt:q.prompt||'',answer:q.answer||'',type:q.type||'word_image',ageGroupId:q.ageGroup?.id??null,subjectId:q.subject?.id??null,answerMode:q.answerMode||'voice',difficulty:Number(q.difficulty)||1,status:q.status||'draft',imageId:q.image?.sha256||q.imageId||null}); optionsText.value=(q.options||[]).join('\n'); active.value='editor' }
const selectedMaterial=computed(()=>materials.value.find(m=>m.sha256===form.imageId))
async function save(){
  saving.value=true
  try{
    const body={prompt:form.prompt,answer:form.answer,type:form.type,ageGroupId:form.ageGroupId,subjectId:form.subjectId,answerMode:form.answerMode,difficulty:Number(form.difficulty),status:form.status,imageId:form.imageId,options:form.answerMode==='choice'?optionsText.value.split('\n').map(x=>x.trim()).filter(Boolean):[]}
    if(form.id) await api(`/api/v1/admin/questions/${form.id}`,{method:'PATCH',body}); else await api('/api/v1/admin/questions',{method:'POST',body})
    active.value=null; toast.value='已保存'; await load()
  }catch(e){toast.value=e.message}finally{saving.value=false}
}
async function toggle(q){ try{ await api(`/api/v1/admin/questions/${q.id}/status`,{method:'POST',body:{status:q.status==='active'?'disabled':'active'}}); toast.value='状态已更新'; active.value=null; await load() }catch(e){toast.value=e.message} }
async function remove(q){ if(!confirm(`删除题目 #${q.id}？`))return; try{ await api(`/api/v1/admin/questions/${q.id}`,{method:'DELETE'}); toast.value='已删除'; await load() }catch(e){toast.value=e.message} }
onMounted(async()=>{ try{await loadMeta()}catch(e){toast.value=e.message} await load() })
</script>
