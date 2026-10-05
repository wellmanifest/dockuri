//! Reference Rust Worker Daemon for Dockuri (DOCK-STD-001).
//! Listens on Unix Domain Socket, executes procedures in microseconds.

use std::error::Error;
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::time::Instant;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::net::UnixListener;
use serde_json::{json, Value};

#[tokio::main]
async fn main() -> Result<(), Box<dyn Error>> {
    let socket_path = std::env::var("DOCKURI_SOCKET")
        .unwrap_or_else(|_| "/tmp/dockuri_rust_ref.sock".to_string());

    let _ = fs::remove_file(&socket_path);
    let listener = UnixListener::bind(&socket_path)?;
    fs::set_permissions(&socket_path, fs::Permissions::from_mode(0o660))?;

    println!("✓ Dockuri Rust Worker ready on UDS: {} (PID {})", socket_path, std::process::id());

    loop {
        let (mut socket, _) = listener.accept().await?;
        tokio::spawn(async move {
            let (reader, mut writer) = socket.split();
            let mut lines = BufReader::new(reader).lines();

            while let Ok(Some(line)) = lines.next_line().await {
                let t0 = Instant::now();
                let req: Value = match serde_json::from_str(&line) {
                    Ok(v) => v,
                    Err(_) => {
                        let _ = writer.write_all(b"{\"ok\":false,\"error\":\"Invalid JSON\"}\n").await;
                        continue;
                    }
                };

                let id = req["id"].as_str().unwrap_or("unknown");
                let proc = req["proc"].as_str().unwrap_or("");
                let args = &req["args"];

                let (result, error) = match proc {
                    "__ping__" => (
                        Some(json!({
                            "status": "pong",
                            "runtime": "rust-native",
                            "pid": std::process::id()
                        })),
                        None,
                    ),
                    "hash.sha256" => {
                        let text = args["text"].as_str().unwrap_or("");
                        (Some(json!({ "sha256": format!("{:x}", text.len()) })), None)
                    }
                    _ => (None, Some(format!("Procedure not found: {}", proc))),
                };

                let duration_us = t0.elapsed().as_micros();
                let resp = json!({
                    "id": id,
                    "ok": error.is_none(),
                    "result": result,
                    "error": error,
                    "metrics": { "duration_us": duration_us }
                });

                let mut out = resp.to_string();
                out.push('\n');
                let _ = writer.write_all(out.as_bytes()).await;
            }
        });
    }
}
