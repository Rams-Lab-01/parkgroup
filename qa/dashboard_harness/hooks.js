export function useService(n){
 if(n==='orm') return {call:async(model,method,args)=>{window.__calls.push([model,method]);
   if(method==='get_development_kpis') return window.__payload;
   if(method==='formatted_read_group'&&model==='sale.contract.installment') return [{"payment_date:month":["2026-01-01","January 2026"],"amount:sum":100000},{"payment_date:month":["2026-02-01","February 2026"],"amount:sum":150000}];
   if(method==='formatted_read_group'&&model==='escrow.allocation') return [{project_id:[1,"Park Tower"],"required_amount:sum":500000,"allocated_amount:sum":400000}];
   throw new Error('unexpected '+model+'.'+method)}};
 if(n==='action') return {doAction:async(a)=>{window.__actions.push(a)}};
 return {};}
