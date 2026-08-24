'use strict';
const crypto=require('node:crypto');

function stable(v){
  if(v===null||typeof v!=='object')return JSON.stringify(v);
  if(Array.isArray(v))return `[${v.map(stable).join(',')}]`;
  return `{${Object.keys(v).sort().map(k=>`${JSON.stringify(k)}:${stable(v[k])}`).join(',')}}`;
}

function signingBytes(result){
  const unsigned={...result};
  delete unsigned.signature;
  return Buffer.from(stable(unsigned));
}

function verifySignedResult({result,publicKey,lifecycle,now=Date.now,maxAgeMs=300000,seenResultIds=new Set()}={}){
  if(!result||typeof result!=='object')throw new Error('SIGNED_RESULT_REQUIRED');
  if(!publicKey)throw new Error('RESULT_PUBLIC_KEY_REQUIRED');
  for(const k of ['resultId','proposalId','proposalHash','postId','requestId','platform','accountId','status','timestamp','signature'])
    if(result[k]===undefined||result[k]===null||result[k]==='')throw new Error(`RESULT_FIELD_REQUIRED:${k}`);
  if(!Number.isFinite(result.timestamp))throw new Error('RESULT_TIMESTAMP_INVALID');
  const age=now()-result.timestamp;
  if(age<0||age>maxAgeMs)throw new Error('RESULT_STALE');
  if(seenResultIds.has(result.resultId))throw new Error('RESULT_DUPLICATE');
  let valid=false;
  try{valid=crypto.verify(null,signingBytes(result),publicKey,Buffer.from(result.signature,'base64url'));}catch{throw new Error('RESULT_SIGNATURE_INVALID');}
  if(!valid)throw new Error('RESULT_SIGNATURE_INVALID');
  const record=lifecycle?.get?.(result.proposalId);
  if(!record)throw new Error('RESULT_PROPOSAL_NOT_FOUND');
  if(record.proposal.proposalHash!==result.proposalHash)throw new Error('RESULT_PROPOSAL_MISMATCH');
  const ext=record.externalExecution;
  if(!ext||ext.postId!==result.postId||ext.requestId!==result.requestId)throw new Error('RESULT_EXECUTION_MISMATCH');
  const target=record.proposal.platforms.find(x=>x.platform===result.platform&&x.accountId===result.accountId);
  if(!target)throw new Error('RESULT_TARGET_MISMATCH');
  seenResultIds.add(result.resultId);
  return Object.freeze({accepted:true,resultId:result.resultId,proposalId:result.proposalId,postId:result.postId,status:result.status});
}

function signResult(result,privateKey){
  const unsigned={...result};delete unsigned.signature;
  return {...unsigned,signature:crypto.sign(null,signingBytes(unsigned),privateKey).toString('base64url')};
}

module.exports={stable,signingBytes,signResult,verifySignedResult};
