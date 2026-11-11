<template>
<div>
<header class="topbar"><div class="crumb">设置 / <b>分类管理</b></div><div class="search">⌕ <span>搜索分类…</span></div><div class="top-actions"><button class="btn" @click="add">＋ 新增</button><div class="avatar">AS</div></div></header>
<div class="content"><div class="page-title"><div><h1>分类管理</h1><p>年龄、学科、题型和素材分类，题库与素材共用。</p></div></div>
<div class="tabs" style="display:inline-flex;margin-bottom:14px"><button class="tab" :class="{on:tab==='age'}" @click="tab='age'">年龄 / 学段</button><button class="tab" :class="{on:tab==='subject'}" @click="tab='subject'">学科</button><button class="tab" :class="{on:tab==='type'}" @click="tab='type'">题型</button><button class="tab" :class="{on:tab==='category'}" @click="tab='category'">素材分类</button></div>
<div class="panel" style="overflow:hidden"><div v-for="item in items" :key="item.id||item.code" style="display:flex;align-items:center;gap:12px;padding:12px 16px;border-bottom:1px solid #f0f4f9"><b style="min-width:180px">{{item.name}}</b><span class="muted" style="flex:1">{{item.code||('排序 '+item.sortOrder)}}</span><span class="pill" :class="item.active===false?'red':'green'">{{item.active===false?'停用':'启用'}}</span><button class="link" @click="edit=item.name">重命名</button></div><div v-if="!items.length" class="empty">暂无分类</div></div>
<div v-if="toast" class="toast">{{toast}}</div></div>
</div>
</template>
<script setup>
import {ref,computed,onMounted,watch} from 'vue'; import {api} from '../api'
const tax=ref({ageGroups:[],subjects:[],questionTypes:[],materialCategories:[]});const tab=ref('age');const toast=ref('');const edit=ref(null)
const items=computed(()=>tab.value==='age'?tax.value.ageGroups:tab.value==='subject'?tax.value.subjects:tab.value==='type'?tax.value.questionTypes:tax.value.materialCategories)
async function load(){tax.value=await api('/api/v1/admin/taxonomies');}
async function add(){const name=prompt('名称');if(!name)return;try{const path=tab.value==='age'?'age-groups':tab.value==='subject'?'subjects':tab.value==='type'?null:'material-categories';if(!path){toast.value='题型请直接编辑种子项';return}await api('/api/v1/admin/'+path,{method:'POST',body:{name}});toast.value='已新增';await load()}catch(e){toast.value=e.message}}
onMounted(()=>load().catch(e=>toast.value=e.message));watch(tab,()=>{})
</script>
