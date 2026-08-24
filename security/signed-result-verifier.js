'use strict';
const crypto=require('node:crypto');
const fs=require('node:fs');
const path=require('node:path');

function stable(v){
  if(v===null||typeof v!=='object')return JSON.stringify(v);
  if(Array.isArray(v))return `[${v.map(stable).join(',')}]`;
  return `{${Object.keys(v).sort().map(k=>`${JSON.stringify(k)}:${stable(v[k])}`).join(',')}}`;
}
function signingBytes(result){const unsigned={...result};delete unsigned.signature;return Buffer.from(stable(unsigned));}
function claimDir(resultJournalPath){return `${path.resolve(resultJournalPath)}.claims`;}
function claimPath(resultJournalPath,resultId){const digest=crypto.createHash('sha256').update(resultId).digest('hex');return path.join(claimDir(resultJournalPath),`${digest}.claim`);}
function loadSeenResultIds(resultJournalPath){
  if(!resultJournalPath)return new Set();
  const seen=new Set();
  if(fs.existsSync(resultJournalPath))for(const line of fs.readFileSync(resultJournalPath,'utf8').split('\n').filter(Boolean)){const e=JSON.parse(line);if(typeof e.resultId!=='string'||!e.resultId)throw new Error('RESULT_JOURNAL_INVALID');seen.add(e.resultId);}
  const dir=claimDir(resultJournalPath);
  if(fs.existsSync(dir))for(const file of fs.readdirSync(dir)){if(!file.endsWith('.claim'))continue;const id=fs.readFileSync(path.join(dir,file),'utf8');if(!id)throw new Error('RESULT_CLAIM_INVALID');seen.add(id);}
  return seen;
}
function atomicClaimResultId(resultJournalPath,resultId){
  if(!resultJournalPath)return true;
  const dir=claimDir(resultJournalPath);fs.mkdirSync(dir,{recursive:true});
  try{
    const fd=fs.openSync(claimPath(resultJournalPath,resultId),'wx',0o600);
    try{fs.writeSync(fd,resultId);fs.fsyncSync(fd);}finally{fs.closeSync(fd);}
    const dirfd=fs.openSync(dir,'r');try{fs.fsyncSync(dirfd);}finally{fs.closeSync(dirfd);}
    return true;
  }catch(err){if(err?.code==='EEXIST')return false;throw err;}
}
function appendResultJournal(resultJournalPath,resultId){
  if(!resultJournalPath)return;
  fs.mkdirSync(path.dirname(path.resolve(resultJournalPath)),{recursive:true});
  const fd=fs.openSync(resultJournalPath,'a',0o600);
  try{fs.writeSync(fd,`${JSON.stringify({resultId})}\n`);fs.fsyncSync(fd);}finally{fs.closeSync(fd);}
}
function verifySignedResult({result,publicKey,lifecycle,now=Date.now,maxAgeMs=300000,seenResultIds,resultJournalPath}={}){
  if(!result||typeof result!=='object')throw new Error('SIGNED_RESULT_REQUIRED');if(!publicKey)throw new Error('RESULT_PUBLIC_KEY_REQUIRED');
  for(const k of ['resultId','proposalId','proposalHash','postId','requestId','platform','accountId','status','timestamp','signature'])if(result[k]===undefined||result[k]===null||result[k]==='')throw new Error(`RESULT_FIELD_REQUIRED:${k}`);
  if(!Number.isFinite(result.timestamp))throw new Error('RESULT_TIMESTAMP_INVALID');const age=now()-result.timestamp;if(age<0||age>maxAgeMs)throw new Error('RESULT_STALE');
  const seen=seenResultIds||loadSeenResultIds(resultJournalPath);if(seen.has(result.resultId))throw new Error('RESULT_DUPLICATE');
  let valid=false;try{valid=crypto.verify(null,signingBytes(result),publicKey,Buffer.from(result.signature,'base64url'));}catch{throw new Error('RESULT_SIGNATURE_INVALID');}if(!valid)throw new Error('RESULT_SIGNATURE_INVALID');
  let record;try{record=lifecycle?.get?.(result.proposalId);}catch(err){if(err?.message==='PROPOSAL_NOT_FOUND')throw new Error('RESULT_PROPOSAL_NOT_FOUND');throw err;}if(!record)throw new Error('RESULT_PROPOSAL_NOT_FOUND');
  if(record.proposal.proposalHash!==result.proposalHash)throw new Error('RESULT_PROPOSAL_MISMATCH');const ext=record.externalExecution;if(!ext||ext.postId!==result.postId||ext.requestId!==result.requestId)throw new Error('RESULT_EXECUTION_MISMATCH');const target=record.proposal.platforms.find(x=>x.platform===result.platform&&x.accountId===result.accountId);if(!target)throw new Error('RESULT_TARGET_MISMATCH');
  if(resultJournalPath){if(!atomicClaimResultId(resultJournalPath,result.resultId))throw new Error('RESULT_DUPLICATE');appendResultJournal(resultJournalPath,result.resultId);}else{if(seenResultIds)seenResultIds.add(result.resultId);}
  return Object.freeze({accepted:true,resultId:result.resultId,proposalId:result.proposalId,postId:result.postId,status:result.status});
}
function signResult(result,privateKey){const unsigned={...result};delete unsigned.signature;return {...unsigned,signature:crypto.sign(null,signingBytes(unsigned),privateKey).toString('base64url')};}
module.exports={stable,signingBytes,signResult,verifySignedResult,loadSeenResultIds};
