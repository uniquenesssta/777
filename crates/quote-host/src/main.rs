use quote_host::{
    auth, backup, fail, files,
    host::{self, Init},
    protocol,
    service::Service,
    Error, Result,
};
use quote_ledger::{integrity, store};
use serde_json::{json, Value};
use std::{
    collections::HashMap,
    path::{Path, PathBuf},
};
struct Args {
    command: String,
    options: HashMap<String, Vec<String>>,
}
impl Args {
    fn parse() -> Result<Self> {
        let mut it = std::env::args().skip(1);
        let command = it
            .next()
            .ok_or_else(|| Error::new(422, "COMMAND_REQUIRED"))?;
        let mut options: HashMap<String, Vec<String>> = HashMap::new();
        while let Some(k) = it.next() {
            if !k.starts_with("--") {
                return fail(422, "ARGUMENT_INVALID");
            }
            let flag = [
                "--auxiliary",
                "--secret-stdin",
                "--old-host-stopped",
                "--upgrade-resources",
                "--test-shutdown-stdin",
                "--shutdown-stdin",
                "--isolated-test",
            ]
            .contains(&k.as_str());
            let value = if flag {
                String::new()
            } else {
                it.next()
                    .ok_or_else(|| Error::new(422, "ARGUMENT_INVALID"))?
            };
            if k != "--host" && options.contains_key(&k) {
                return fail(422, "DUPLICATE_ARGUMENT");
            };
            options.entry(k).or_default().push(value);
        }
        let a = Self { command, options };
        let allowed = match a.command.as_str() {
            "init" => vec![
                "--root",
                "--backup-dir",
                "--host",
                "--bind",
                "--port",
                "--admin",
                "--worker",
                "--notices",
                "--auxiliary",
                "--secret-stdin",
            ],
            "run" => vec![
                "--root",
                "--shutdown-stdin",
                "--auxiliary",
                "--test-shutdown-stdin",
                "--isolated-test",
                "--test-fault-file",
                "--auxiliary-font",
                "--test-font-file",
            ],
            "inspect" => vec!["--root", "--auxiliary"],
            "authorize" => vec!["--root", "--admin", "--auxiliary", "--secret-stdin"],
            "configure-daily" => vec![
                "--root",
                "--backup-dir",
                "--hidden-dir",
                "--daily-hour",
                "--admin",
                "--auxiliary",
                "--secret-stdin",
            ],
            "restore-data" => vec![
                "--root",
                "--package",
                "--backup-dir",
                "--host",
                "--bind",
                "--port",
                "--admin",
                "--worker",
                "--notices",
                "--auxiliary",
                "--secret-stdin",
            ],
            "configure-backup" => vec![
                "--root",
                "--backup-dir",
                "--admin",
                "--auxiliary",
                "--secret-stdin",
            ],
            "enable-devices" => vec!["--root", "--admin", "--auxiliary", "--secret-stdin"],
            "backup" => vec![
                "--root",
                "--kind",
                "--admin",
                "--auxiliary",
                "--secret-stdin",
            ],
            "restore" => vec![
                "--package",
                "--root",
                "--admin",
                "--auxiliary",
                "--secret-stdin",
            ],
            "select-host" => vec![
                "--root",
                "--admin",
                "--backend",
                "--worker",
                "--notices",
                "--upgrade-resources",
                "--auxiliary",
                "--secret-stdin",
            ],
            "activate-restored" => vec!["--root", "--old-host-stopped", "--auxiliary"],
            _ => return fail(422, "UNKNOWN_COMMAND"),
        };
        if a.options.keys().any(|k| !allowed.contains(&k.as_str())) {
            return fail(422, "ARGUMENT_INVALID");
        }
        if a.has("--auxiliary") && cfg!(windows) {
            return fail(400, "WINDOWS_SECURITY_CANNOT_BE_DISABLED");
        }
        if !a.has("--auxiliary") && !cfg!(windows) {
            return fail(400, "WINDOWS_HOST_REQUIRED");
        }
        Ok(a)
    }
    fn has(&self, k: &str) -> bool {
        self.options.contains_key(k)
    }
    fn get(&self, k: &str) -> Result<&str> {
        self.options
            .get(k)
            .and_then(|v| v.first())
            .map(String::as_str)
            .ok_or_else(|| Error::new(422, "ARGUMENT_REQUIRED"))
    }
    fn default<'a>(&'a self, k: &str, d: &'a str) -> &'a str {
        self.get(k).unwrap_or(d)
    }
    fn path(&self, k: &str) -> Result<PathBuf> {
        Ok(PathBuf::from(self.get(k)?))
    }
    fn secret(&self, confirm: bool) -> Result<String> {
        if self.has("--secret-stdin") {
            use std::io::Read;
            let mut raw = vec![];
            std::io::stdin().take(2049).read_to_end(&mut raw)?;
            let data = protocol::decode(&raw, 2048)?;
            protocol::fields(&data, &["password"], &[])?;
            if confirm {
                Ok(auth::password(&data["password"])?.into())
            } else {
                Ok(protocol::text(&data["password"], 128, true)?.into())
            }
        } else {
            let secret = rpassword::prompt_password("管理员密码（不回显）：")?;
            if confirm {
                auth::password(&json!(secret))?;
            } else {
                protocol::text(&json!(secret), 128, true)?;
            }
            if confirm && rpassword::prompt_password("再次输入密码：")? != secret {
                return fail(422, "PASSWORD_CONFIRMATION_MISMATCH");
            }
            Ok(secret)
        }
    }
}
async fn execute(a: Args) -> Result<Value> {
    let auxiliary = a.has("--auxiliary");
    let root = a.path("--root")?;
    match a.command.as_str(){
  "init"=>{let config=host::initialize(Init{root,backups:a.path("--backup-dir")?,hosts:a.options.get("--host").cloned().unwrap_or_default(),bind:a.default("--bind","127.0.0.1").into(),port:a.default("--port","8477").parse().map_err(|_|Error::new(422,"HOST_CONFIG_INVALID"))?,user:a.default("--admin","manager").into(),secret:a.secret(true)?,worker:a.path("--worker")?,notices:a.path("--notices")?,auxiliary})?;Ok(json!({"status":"initialized_not_started","ledger_id":config["ledger_id"],"certificate_sha256":config["certificate_sha256"],"host_backend":"rust"}))},
  "run"=>{let mut service=Service::load(&root,auxiliary,false)?;if (a.has("--test-fault-file")||a.has("--test-shutdown-stdin"))&&!a.has("--isolated-test"){return fail(422,"ISOLATED_TEST_FLAG_REQUIRED")}
   if a.has("--test-fault-file"){let p=a.path("--test-fault-file")?;if p.parent()!=Some(root.join("private").as_path()){return fail(422,"TEST_PATH_OUTSIDE_HOST")};service.test_fault=Some(p);}
   if a.has("--test-font-file"){if !a.has("--isolated-test"){return fail(422,"ISOLATED_TEST_FLAG_REQUIRED")};let path=a.path("--test-font-file")?;files::local(&path,true)?;service.font=Some(path);}
   if a.has("--auxiliary-font"){if cfg!(windows)||!auxiliary||!a.has("--isolated-test"){return fail(422,"AUXILIARY_FONT_FORBIDDEN")};service.font=Some(a.path("--auxiliary-font")?);}host::serve(service,a.has("--shutdown-stdin")||a.has("--test-shutdown-stdin")).await?;Ok(json!({"status":"stopped","ownership_released":true}))},
  "enable-devices"=>{let _owner=files::Owner::acquire(&root)?;let mut s=Service::load(&root,auxiliary,true)?;let login=s.auth.login(&json!(a.get("--admin")?),&json!(a.secret(false)?),"enable-devices")?;let token=login["token"].as_str().unwrap();let result=(||{auth::Auth::admin(&s.auth.authenticate(token)?)?;if s.devices.is_some(){return Ok(json!({"status":"already_enabled"}))};quote_host::devices::Devices::create(&root.join("private/devices.sqlite3"))?;s.config["device_auth"]=json!(quote_host::devices::FORMAT);files::replace_json(&root.join("private/service.json"),&s.config)?;Ok(json!({"status":"device_auth_enabled_restart_required"}))})();let _=s.auth.logout(token);result},
  "inspect"=>{let s=Service::load(&root,auxiliary,true)?;Ok(json!({"inventory":integrity::inventory(&store::open(&s.ledger,false)?)?,"maintenance":s.config["maintenance"],"host_backend":s.config.get("service_backend").unwrap_or(&json!("python")),"private_security":s.config["private_security"],"certificate_sha256":s.config["certificate_sha256"],"shutdown_control":"stdin-v1"}))},
  "authorize"=>quote_host::operator::authorize(&root,a.get("--admin")?,&a.secret(false)?,auxiliary),
  "configure-daily"=>quote_host::operator::configure_daily(&root,&a.path("--backup-dir")?,&a.path("--hidden-dir")?,a.default("--daily-hour","23").parse().map_err(|_|Error::new(422,"DAILY_BACKUP_CONFIG_INVALID"))?,a.get("--admin")?,&a.secret(false)?,auxiliary),
  "restore-data"=>quote_host::recovery::restore(&a.path("--package")?,Init{root,backups:a.path("--backup-dir")?,hosts:a.options.get("--host").cloned().unwrap_or_default(),bind:a.default("--bind","127.0.0.1").into(),port:a.default("--port","8477").parse().map_err(|_|Error::new(422,"HOST_CONFIG_INVALID"))?,user:a.get("--admin")?.into(),secret:a.secret(true)?,worker:a.path("--worker")?,notices:a.path("--notices")?,auxiliary}),
  "configure-backup"=>quote_host::operator::configure_backup(&root,&a.path("--backup-dir")?,a.get("--admin")?,&a.secret(false)?,auxiliary),
  "backup"=>{let _owner=files::Owner::acquire(&root)?;let mut s=Service::load(&root,auxiliary,true)?;let login=s.auth.login(&json!(a.get("--admin")?),&json!(a.secret(false)?),"offline-backup")?;let token=login["token"].as_str().unwrap();let actor=s.auth.authenticate(token)?;let result=(||{auth::Auth::admin(&actor)?;backup::create(&s,a.default("--kind","maintenance"))})();let _=s.auth.logout(token);result},
  "restore"=>backup::restore(&a.path("--package")?,&root,a.get("--admin")?,&a.secret(true)?,auxiliary),
  "select-host"=>host::select(host::Selection{root:&root,user:a.get("--admin")?,password:&a.secret(false)?,backend:a.get("--backend")?,worker:a.get("--worker").ok().map(Path::new),notices:a.get("--notices").ok().map(Path::new),upgrade:a.has("--upgrade-resources"),auxiliary}).map(|v|json!({"status":"selected_not_started","service_backend":v["service_backend"],"ledger_id":v["ledger_id"]})),
  "activate-restored"=>{if !a.has("--old-host-stopped"){return fail(422,"OLD_HOST_STOP_CONFIRMATION_REQUIRED")};let _owner=files::Owner::acquire(&root)?;let s=Service::load(&root,auxiliary,true)?;if s.config["maintenance"]!=true{return fail(409,"RECOVERY_MAINTENANCE_REQUIRED")};let mut config=s.config;config["maintenance"]=json!(false);files::replace_json(&root.join("private/service.json"),&config)?;Ok(json!({"status":"activation_registered_not_started"}))},
  _=>fail(422,"UNKNOWN_COMMAND")
 }
}
#[tokio::main(flavor = "multi_thread", worker_threads = 4)]
async fn main() {
    quote_diagnostics::init("host");
    let result = match Args::parse() {
        Ok(a) => {
            let command = a.command.clone();
            quote_diagnostics::event("command.start", json!({"command":command}));
            let result = execute(a).await;
            quote_diagnostics::event(
                "command.finish",
                json!({"command":command,"error":result.as_ref().err().map(|e|&e.code)}),
            );
            result
        }
        Err(e) => Err(e),
    };
    quote_diagnostics::event("runtime.stop", json!({"ok":result.is_ok()}));
    match result {
        Ok(v) => println!("{}", v),
        Err(e) => {
            eprintln!("{}", json!({"status":"failed","error":e.code}));
            std::process::exit(1);
        }
    }
}
