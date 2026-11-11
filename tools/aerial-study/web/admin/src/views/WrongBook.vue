<template><div><div class="page-head"><div><h1>错题本</h1><p class="muted">按题目汇总错误次数与错误率</p></div><button @click="load">刷新</button></div>
<div class="panel"><div class="table-wrap"><table><thead><tr><th>题目</th><th>错误</th><th>总次数</th><th>错误率</th><th>最近错误</th></tr></thead><tbody><tr v-for="x in items" :key="x.question_id"><td><strong>{{x.prompt}}</strong><div class="muted">#{{x.question_id}}</div></td><td>{{x.wrong_attempts}}</td><td>{{x.total_attempts}}</td><td>{{Math.round(x.wrongRate*100)}}%</td><td>{{x.last_wrong_at}}</td></tr></tbody></table></div><p v-if="!items.length" class="muted">暂无错题</p></div><div class="toast" v-if="toast">{{toast}}</div></div></template>
<script setup>
import {ref,onMounted} from 'vue'; import {api} from '../api'
const items=ref([]); const toast=ref('')
async function load(){ try{ items.value=(await api('/api/v1/admin/wrong-questions?limit=200')).items }catch(e){toast.value=e.message} }
onMounted(load)
</script>
