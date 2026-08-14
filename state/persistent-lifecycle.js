'use strict';

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

const STATES = Object.freeze(['CREATED','HASHED','BUILT','SIMULATED','TIMELOCKED','RE_SIMULATED','APPROVED','SIGNED','BROADCAST','CONFIRMED','VERIFIED','REJECTED']);
const TRANSITIONS = Object.freeze({CREATED:['HASHED','REJECTED'],HASHED:['BUILT','REJECTED'],BUILT:['SIMULATED','REJECTED'],SIMULATED:['TIMELOCKED','REJECTED'],TIMELOCKED:['RE_SIMULATED','REJECTED'],RE_SIMULATED:['APPROVED','REJECTED'],APPROVED:['SIGNED','REJECTED'],SIGNED:['BROADCAST','REJECTED'],BROADCAST:['CONFIRMED','REJECTED'],CONFIRMED:['VERIFIED','REJECTED'],VERIFIED:[],REJECTED:[]});

function stable(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stable).join(',')}]`;
  return `{${Object.keys(value).sort().map(k => `${JSON.stringify(k)}:${stable(value[k])}`).join(',')}}`;
}
function hash(value) { return crypto.createHash('sha256').update(stable(value)).digest('hex'); }

class PersistentLifecycle {
  constructor(filePath, { clock = () => Date.now() } = {}) {
    if (!filePath) throw new TypeError('LIFECYCLE_PATH_REQUIRED');
    this.filePath = path.resolve(filePath); this.clock = clock;
    fs.mkdirSync(path.dirname(this.filePath), { recursive: true });
    if (!fs.existsSync(this.filePath)) fs.writeFileSync(this.filePath, '', { mode: 0o600 });
    this.records = new Map(); this.lastAuditHash = 'GENESIS'; this._recover();
  }

  createProposal(proposal) {
    if (!proposal || !proposal.proposalId || !proposal.proposalHash) throw new Error('IMMUTABLE_PROPOSAL_REQUIRED');
    if (this.records.has(proposal.proposalId)) throw new Error('PROPOSAL_ALREADY_EXISTS');
    const record = { proposal: JSON.parse(JSON.stringify(proposal)), state:'CREATED', version:0, transactionBindingHash:null, timelockUntil:null, simulationBindingHash:null, approval:null };
    this.records.set(proposal.proposalId, record);
    this._transition(record, 'CREATED', { proposal: record.proposal });
    return this.get(proposal.proposalId);
  }

  transition(proposalId, nextState, payload = {}, expectedVersion) {
    const record = this._require(proposalId);
    if (expectedVersion !== undefined && expectedVersion !== record.version) throw new Error('VERSION_CONFLICT');
    if (!STATES.includes(nextState)) throw new Error('UNKNOWN_STATE');
    this._transition(record, nextState, payload); return this.get(proposalId);
  }

  bindTransaction(proposalId, transactionBindingHash) {
    if (!transactionBindingHash) throw new Error('TRANSACTION_BINDING_REQUIRED');
    const record = this._require(proposalId);
    if (record.state !== 'HASHED') throw new Error('INVALID_TRANSACTION_BINDING_STATE');
    record.transactionBindingHash = transactionBindingHash;
    this._transition(record, 'BUILT', { transactionBindingHash }); return this.get(proposalId);
  }

  recordSimulation(proposalId, transactionBindingHash, { success, phase='initial' } = {}) {
    const record = this._require(proposalId);
    if (record.transactionBindingHash !== transactionBindingHash) throw new Error('TRANSACTION_BINDING_MISMATCH');
    if (!success) throw new Error('SIMULATION_FAILED');
    if (phase === 'initial') this._transition(record, 'SIMULATED', { transactionBindingHash });
    else if (phase === 'resimulation') {
      if (record.state !== 'TIMELOCKED') throw new Error('RESIMULATION_NOT_ALLOWED');
      if (this.clock() < record.timelockUntil) throw new Error('TIMELOCK_ACTIVE');
      record.simulationBindingHash = transactionBindingHash;
      this._transition(record, 'RE_SIMULATED', { transactionBindingHash });
    } else throw new Error('UNKNOWN_SIMULATION_PHASE');
    return this.get(proposalId);
  }

  startTimelock(proposalId, durationMs=172800000) {
    const record=this._require(proposalId);
    if(record.state!=='SIMULATED') throw new Error('TIMELOCK_REQUIRES_SIMULATION');
    if(!Number.isSafeInteger(durationMs)||durationMs<=0) throw new Error('INVALID_TIMELOCK');
    record.timelockUntil=this.clock()+durationMs;
    this._transition(record,'TIMELOCKED',{timelockUntil:record.timelockUntil}); return this.get(proposalId);
  }

  approve(proposalId, approvalId) {
    const record=this._require(proposalId);
    if(record.state!=='RE_SIMULATED') throw new Error('APPROVAL_REQUIRES_RESIMULATION');
    if(record.simulationBindingHash!==record.transactionBindingHash) throw new Error('SIMULATION_BINDING_MISMATCH');
    if(this.clock()<record.timelockUntil) throw new Error('TIMELOCK_ACTIVE');
    record.approval={approvalId,proposalHash:record.proposal.proposalHash,transactionBindingHash:record.transactionBindingHash};
    this._transition(record,'APPROVED',{approvalId,transactionBindingHash:record.transactionBindingHash}); return this.get(proposalId);
  }

  get(proposalId) { return Object.freeze(JSON.parse(JSON.stringify(this._require(proposalId)))); }

  verifyAuditChain() {
    let previous='GENESIS';
    for(const line of fs.readFileSync(this.filePath,'utf8').split('\n').filter(Boolean)) {
      const event=JSON.parse(line); if(event.previousHash!==previous) throw new Error('AUDIT_CHAIN_BROKEN');
      const {eventHash,...unsigned}=event; if(hash(unsigned)!==eventHash) throw new Error('AUDIT_EVENT_TAMPERED'); previous=eventHash;
    }
    return true;
  }

  _require(id){const record=this.records.get(id);if(!record)throw new Error('PROPOSAL_NOT_FOUND');return record;}
  _transition(record,nextState,payload){
    if(record.state!==nextState&&!(TRANSITIONS[record.state]||[]).includes(nextState)) throw new Error(`INVALID_TRANSITION:${record.state}->${nextState}`);
    const previousState=record.state; record.state=nextState; record.version+=1;
    this._append({type:'STATE_TRANSITION',proposalId:record.proposal.proposalId,proposalHash:record.proposal.proposalHash,previousState,nextState,version:record.version,payload});
  }
  _append(data){
    const unsigned={timestamp:this.clock(),previousHash:this.lastAuditHash,...data}; const event={...unsigned,eventHash:hash(unsigned)};
    fs.appendFileSync(this.filePath,`${JSON.stringify(event)}\n`,{encoding:'utf8'}); const fd=fs.openSync(this.filePath,'r'); try{fs.fsyncSync(fd);}finally{fs.closeSync(fd)} this.lastAuditHash=event.eventHash;
  }
  _recover(){
    let previous='GENESIS';
    for(const line of fs.readFileSync(this.filePath,'utf8').split('\n').filter(Boolean)){
      const event=JSON.parse(line); if(event.previousHash!==previous)throw new Error('AUDIT_CHAIN_BROKEN');
      const {eventHash,...unsigned}=event; if(hash(unsigned)!==eventHash)throw new Error('AUDIT_EVENT_TAMPERED'); previous=eventHash;
      let record=this.records.get(event.proposalId);
      if(!record){
        record={proposal:event.payload?.proposal||{proposalId:event.proposalId,proposalHash:event.proposalHash},state:event.nextState,version:event.version,transactionBindingHash:null,timelockUntil:null,simulationBindingHash:null,approval:null};
        this.records.set(event.proposalId,record);
      } else { record.state=event.nextState; record.version=event.version; }
      const p=event.payload||{};
      if(p.transactionBindingHash) record.transactionBindingHash=p.transactionBindingHash;
      if(p.timelockUntil !== undefined) record.timelockUntil=p.timelockUntil;
      if(event.nextState==='RE_SIMULATED' && p.transactionBindingHash) record.simulationBindingHash=p.transactionBindingHash;
      if(event.nextState==='APPROVED' && p.approvalId) record.approval={approvalId:p.approvalId,proposalHash:event.proposalHash,transactionBindingHash:p.transactionBindingHash};
    }
    this.lastAuditHash=previous;
  }
}
module.exports={PersistentLifecycle,STATES,TRANSITIONS};
