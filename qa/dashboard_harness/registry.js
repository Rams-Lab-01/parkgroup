const cats={};export const registry={category:(n)=>(cats[n]??={_m:new Map(),add(k,v){this._m.set(k,v)},get(k,d){return this._m.get(k)??d},contains(k){return this._m.has(k)}})};window.__registry=cats;
