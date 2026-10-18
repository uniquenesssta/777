export type IssuerState={ready:boolean;phase:string;site_id?:string;ledger_id?:string;interfaces:string[]};
export type PackageJob={id:string;state:'running'|'cancelling'|'cancelled'|'failed'|'succeeded';delivery:string;permissions?:string[];version:string;output:string;lines:string[];error:string|null;bytes:number|null;source_commit?:string};
export type PackageConfiguration={preferences:{output:string;version:string;runtime:string};job:PackageJob|null;issuer:IssuerState};
