<template><div><div class="page-head"><div><h1>答题记录</h1><p class="muted">会话进度与每次作答</p></div><button @click="load">刷新</button></div>
<div class="panel"><div class="table-wrap"><table><thead><tr><th>会话</th><th>状态</th><th>进度</th><th>创建时间</th><th></th></tr></thead><tbody><tr v-for="s in items" :key="s.id"><td class="muted">{{s.id}}</td><td>{{s.status}}</td><td>{{s.correct}} / {{s.wrong}} · {{s.total}}</td><td>{{s.createdAt}}</td><td><button class="small ghost" @click="open(s)">详情</button></td></tr></tbody></table></div></div>
<div v-if="detail" class="panel"><h2>会话详情</h2><pre style="white-space:pre-wrap;font-size:12px">{{JSON.stringify(detail,null,2)}}</pre></div>
<div class="toast" v-if="toast">{{toast}}</div></div></template>
<script setup>
import {ref,onMounted} from 'vue'; import {api} from '../api'
const items=ref([]); const detail=ref(null); const toast=ref('')
async function load(){ try{ items.value=(await api('/api/v1/admin/records?limit=100')).items }catch(e){toast.value=e.message} }
async function open(s){ try{ detail.value=await api('/api/v1/admin/records/'+s.id) }catch(e){toast.value=e.message} }
onMounted(load)
</script>
