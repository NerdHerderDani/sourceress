use clap::{Parser, Subcommand};
use rand::{distributions::Alphanumeric, Rng};
use serde_json::{json, Value};
use std::io::{self, BufRead, Write};

#[derive(Parser, Debug)]
#[command(name = "SourceressConnector", version, about = "Local MCP connector for Sourceress")]
struct Cli {
    /// Sourceress base URL (default: autodetect then http://127.0.0.1:8000)
    #[arg(long)]
    base_url: Option<String>,

    /// Optional bearer token for Sourceress (if auth bypass is disabled)
    #[arg(long)]
    bearer: Option<String>,

    #[command(subcommand)]
    cmd: Command,
}

#[derive(Subcommand, Debug)]
enum Command {
    /// Generate a per-machine agent key and set it in Sourceress.
    Install,

    /// Run the MCP stdio server.
    Start,

    /// Print status about connectivity.
    Status,
}

fn detect_base_url() -> String {
    let candidates = [
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        // fallback ports (if user runs multiple instances)
        "http://127.0.0.1:8010",
        "http://127.0.0.1:8080",
    ];

    for u in candidates {
        if let Ok(resp) = ureq::get(&format!("{}/health", u)).call() {
            if resp.status() == 200 {
                return u.to_string();
            }
        }
    }

    "http://127.0.0.1:8000".to_string()
}

fn gen_key() -> String {
    rand::thread_rng()
        .sample_iter(&Alphanumeric)
        .take(48)
        .map(char::from)
        .collect()
}

fn auth_headers(bearer: &Option<String>, agent_key: Option<&str>) -> Vec<(String, String)> {
    let mut h = vec![
        ("Content-Type".to_string(), "application/json".to_string()),
    ];
    if let Some(b) = bearer {
        if !b.trim().is_empty() {
            h.push(("Authorization".to_string(), format!("Bearer {}", b.trim())));
        }
    }
    if let Some(k) = agent_key {
        h.push(("X-Sourceress-Agent-Key".to_string(), k.to_string()));
    }
    h
}

fn post_json(url: &str, bearer: &Option<String>, agent_key: Option<&str>, body: Value) -> anyhow::Result<Value> {
    let mut req = ureq::post(url);
    for (k, v) in auth_headers(bearer, agent_key) {
        req = req.set(&k, &v);
    }
    let resp = req.send_json(body)?;
    let val: Value = resp.into_json()?;
    Ok(val)
}

fn main() -> anyhow::Result<()> {
    let cli = Cli::parse();

    let base = cli.base_url.unwrap_or_else(detect_base_url);

    match cli.cmd {
        Command::Install => {
            let key = gen_key();
            let url = format!("{}/agent/key/set", base);
            let out = post_json(&url, &cli.bearer, None, json!({"key": key}))?;
            if out.get("ok").and_then(|v| v.as_bool()) != Some(true) {
                eprintln!("Install failed: {}", out);
                std::process::exit(1);
            }

            println!("OK: agent key set on Sourceress");
            println!("BASE_URL={}", base);
            println!("AGENT_KEY={}", key);
            println!();
            println!("Claude Desktop MCP config (example):");
            println!("{{");
            println!("  \"mcpServers\": {{");
            println!("    \"sourceress\": {{");
            println!("      \"command\": \"{}\",");
            println!("      \"args\": [\"--base-url\", \"{}\", \"start\"],");
            println!("      \"env\": {{ \"SOURCERESS_AGENT_KEY\": \"{}\" }}");
            println!("    }}");
            println!("  }}");
            println!("}}");
        }
        Command::Status => {
            let health = ureq::get(&format!("{}/health", base)).call();
            println!("BASE_URL={}", base);
            println!("health={}", if health.is_ok() { "ok" } else { "error" });
        }
        Command::Start => {
            // MCP stdio loop
            let agent_key = std::env::var("SOURCERESS_AGENT_KEY").unwrap_or_default();
            if agent_key.trim().is_empty() {
                eprintln!("Missing SOURCERESS_AGENT_KEY env var. Run: SourceressConnector install");
                std::process::exit(2);
            }

            let stdin = io::stdin();
            let mut stdout = io::stdout();

            for line in stdin.lock().lines() {
                let line = line?;
                let req: Value = match serde_json::from_str(&line) {
                    Ok(v) => v,
                    Err(_) => continue,
                };

                let id = req.get("id").cloned().unwrap_or(Value::Null);
                let method = req.get("method").and_then(|m| m.as_str()).unwrap_or("");

                let resp = match method {
                    "initialize" => {
                        json!({
                            "jsonrpc":"2.0",
                            "id": id,
                            "result": {
                                "protocolVersion": "2024-11-05",
                                "capabilities": {
                                    "tools": {}
                                },
                                "serverInfo": {
                                    "name": "sourceress",
                                    "version": "0.1.0"
                                }
                            }
                        })
                    }
                    "tools/list" => {
                        json!({
                            "jsonrpc":"2.0",
                            "id": id,
                            "result": {
                                "tools": [
                                    {
                                        "name": "sourceress.company_upsert",
                                        "description": "Create/update a company in Talent Mapping (name, tags, links)",
                                        "inputSchema": {
                                            "type": "object",
                                            "properties": {
                                                "name": {"type":"string"},
                                                "tags": {"type":"string"},
                                                "github_org_url": {"type":"string"},
                                                "linkedin_company_url": {"type":"string"},
                                                "jobs_url": {"type":"string"}
                                            },
                                            "required": ["name"]
                                        }
                                    },
                                    {
                                        "name": "sourceress.comp_import_csv",
                                        "description": "Import comp rows from CSV/TSV text for a company",
                                        "inputSchema": {
                                            "type": "object",
                                            "properties": {
                                                "company_name": {"type":"string"},
                                                "dept": {"type":"string", "default":"engineering"},
                                                "csv_text": {"type":"string"},
                                                "source_url": {"type":"string"}
                                            },
                                            "required": ["company_name", "csv_text"]
                                        }
                                    }
                                ]
                            }
                        })
                    }
                    "tools/call" => {
                        let name = req.get("params").and_then(|p| p.get("name")).and_then(|v| v.as_str()).unwrap_or("");
                        let args = req.get("params").and_then(|p| p.get("arguments")).cloned().unwrap_or(json!({}));

                        let result = match name {
                            "sourceress.company_upsert" => {
                                let url = format!("{}/agent/company/upsert", base);
                                post_json(&url, &cli.bearer, Some(agent_key.trim()), args)
                            }
                            "sourceress.comp_import_csv" => {
                                let url = format!("{}/agent/company/comp/import_csv", base);
                                post_json(&url, &cli.bearer, Some(agent_key.trim()), args)
                            }
                            _ => Ok(json!({"ok": false, "error": "unknown tool"})),
                        };

                        let content = match result {
                            Ok(v) => json!([{"type":"text", "text": v.to_string()}]),
                            Err(e) => json!([{"type":"text", "text": format!("error: {}", e)}]),
                        };

                        json!({
                            "jsonrpc":"2.0",
                            "id": id,
                            "result": {"content": content}
                        })
                    }
                    _ => {
                        json!({
                            "jsonrpc":"2.0",
                            "id": id,
                            "error": {"code": -32601, "message": "Method not found"}
                        })
                    }
                };

                writeln!(stdout, "{}", resp.to_string())?;
                stdout.flush()?;
            }
        }
    }

    Ok(())
}
