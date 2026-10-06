use std::collections::HashMap;
use std::fs::File;
use std::io::BufReader;
use std::path::{Path, PathBuf};
use std::time::Instant;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use walkdir::{DirEntry, WalkDir};

const EXCLUDED: &[&str] = &[
    ".git", ".hg", ".svn", "node_modules", "venv", ".venv", "target",
    "dist", "build", ".pytest_cache", ".cache", ".idea", ".vscode",
    ".worktrees", ".subactor", ".code2llm_cache", "logs", "conversations"
];

#[derive(Debug, Deserialize, Serialize)]
struct ProcedureDef {
    #[serde(default)]
    description: String,
    #[serde(default = "default_effect")]
    effect: String,
    #[serde(default)]
    schema: serde_json::Value,
}

fn default_effect() -> String {
    "pure".to_string()
}

#[derive(Debug, Deserialize, Serialize)]
struct Manifest {
    app: String,
    #[serde(default)]
    version: String,
    #[serde(default)]
    transport: serde_json::Value,
    #[serde(default)]
    procedures: HashMap<String, ProcedureDef>,
}

#[derive(Debug, Deserialize)]
struct SingleProcManifest {
    #[serde(default)]
    format: Option<String>,
    uri: String,
    #[serde(default)]
    desc: String,
    #[serde(default)]
    effects: Vec<String>,
}

fn parse_yaml_proc(content: &str) -> Option<(String, String, String, String, String)> {
    let mut uri = None;
    let mut desc = None;
    let mut effect = "pure".to_string();

    let mut in_effects = false;
    for line in content.lines() {
        let trimmed = line.trim();
        if trimmed.starts_with("uri:") {
            in_effects = false;
            let val = trimmed["uri:".len()..].trim().trim_matches(|c| c == '"' || c == '\'');
            uri = Some(val.to_string());
        } else if trimmed.starts_with("desc:") {
            in_effects = false;
            let val = trimmed["desc:".len()..].trim().trim_matches(|c| c == '"' || c == '\'');
            desc = Some(val.to_string());
        } else if trimmed.starts_with("effects:") {
            in_effects = true;
        } else if in_effects && trimmed.starts_with("- ") {
            let eff = trimmed["- ".len()..].trim().trim_matches(|c| c == '"' || c == '\'');
            if !eff.is_empty() {
                effect = eff.to_string();
                in_effects = false;
            }
        } else if !trimmed.starts_with('#') && !trimmed.is_empty() && !trimmed.starts_with('-') {
            in_effects = false;
        }
    }

    if let Some(u) = uri {
        let parts: Vec<&str> = u.trim_start_matches("proc://").split('/').collect();
        let app = if parts.len() >= 2 { parts[1].to_string() } else { "app".to_string() };
        let proc_name = if parts.len() >= 3 { parts[2].to_string() } else { "main".to_string() };
        let d = desc.unwrap_or_else(|| proc_name.clone());
        Some((app, proc_name, u, d, effect))
    } else {
        None
    }
}

#[derive(Debug, Serialize, Deserialize)]
struct IndexedProcedure {
    app: String,
    proc_name: String,
    uri: String,
    desc: String,
    effect: String,
    contract_digest: String,
    manifest_path: PathBuf,
}

#[derive(Debug, Deserialize)]
struct ConnectorManifest {
    #[serde(default)]
    id: Option<String>,
    #[serde(default)]
    name: Option<String>,
    #[serde(default)]
    summary: String,
    #[serde(default)]
    description: String,
    #[serde(default)]
    routes: Vec<String>,
}

fn is_excluded(entry: &DirEntry) -> bool {
    let ft = entry.file_type();
    if ft.is_symlink() {
        return true;
    }
    if ft.is_dir() {
        let name = entry.file_name().to_string_lossy();
        if (entry.depth() > 0 && name.starts_with('.')) || EXCLUDED.iter().any(|&ex| ex == name) {
            return true;
        }
    }
    false
}

fn scan_directory<P: AsRef<Path>>(root: P) -> (Vec<IndexedProcedure>, usize) {
    let mut procs = Vec::new();
    let mut manifests_found = 0;

    let walker = WalkDir::new(root).into_iter().filter_entry(|e| !is_excluded(e));

    for entry in walker.filter_map(Result::ok) {
        let fname = entry.file_name().to_string_lossy();
        if entry.file_type().is_file() {
            let is_dockuri_json = fname == "dockuri.json" || fname.ends_with(".proc.json");
            let is_proc_yaml = fname == "dockuri.proc.yaml" || fname == "proc.yaml" || fname.ends_with(".proc.yaml") || fname.ends_with(".proc.yml");

            if is_dockuri_json {
                manifests_found += 1;
                let path = entry.into_path();
                if let Ok(content) = std::fs::read_to_string(&path) {
                    if let Ok(single) = serde_json::from_str::<SingleProcManifest>(&content) {
                        let parts: Vec<&str> = single.uri.trim_start_matches("proc://").split('/').collect();
                        let app = if parts.len() >= 2 { parts[1].to_string() } else { "app".to_string() };
                        let proc_name = if parts.len() >= 3 { parts[2].to_string() } else { "main".to_string() };
                        let effect = single.effects.first().cloned().unwrap_or_else(|| "pure".to_string());

                        let mut hasher = Sha256::new();
                        hasher.update(single.uri.as_bytes());
                        hasher.update(single.desc.as_bytes());
                        hasher.update(effect.as_bytes());
                        let hash_bytes = hasher.finalize();
                        let digest = hash_bytes.iter().map(|b| format!("{:02x}", b)).collect::<String>();

                        procs.push(IndexedProcedure {
                            app,
                            proc_name,
                            uri: single.uri,
                            desc: single.desc,
                            effect,
                            contract_digest: digest,
                            manifest_path: path.clone(),
                        });
                    } else if let Ok(manifest) = serde_json::from_str::<Manifest>(&content) {
                        for (proc_name, def) in manifest.procedures {
                            let uri = format!("proc://{}/{}/v1", manifest.app, proc_name.replace('.', "/"));
                            
                            let mut hasher = Sha256::new();
                            hasher.update(uri.as_bytes());
                            hasher.update(def.description.as_bytes());
                            hasher.update(def.effect.as_bytes());
                            let hash_bytes = hasher.finalize();
                            let digest = hash_bytes.iter().map(|b| format!("{:02x}", b)).collect::<String>();

                            procs.push(IndexedProcedure {
                                app: manifest.app.clone(),
                                proc_name,
                                uri,
                                desc: def.description,
                                effect: def.effect,
                                contract_digest: digest,
                                manifest_path: path.clone(),
                            });
                        }
                    }
                }
            } else if is_proc_yaml {
                manifests_found += 1;
                let path = entry.into_path();
                if let Ok(content) = std::fs::read_to_string(&path) {
                    if let Some((app, proc_name, uri, desc, effect)) = parse_yaml_proc(&content) {
                        let mut hasher = Sha256::new();
                        hasher.update(uri.as_bytes());
                        hasher.update(desc.as_bytes());
                        hasher.update(effect.as_bytes());
                        let hash_bytes = hasher.finalize();
                        let digest = hash_bytes.iter().map(|b| format!("{:02x}", b)).collect::<String>();

                        procs.push(IndexedProcedure {
                            app,
                            proc_name,
                            uri,
                            desc,
                            effect,
                            contract_digest: digest,
                            manifest_path: path.clone(),
                        });
                    }
                }
            } else if fname == "connector.manifest.json" {
                manifests_found += 1;
                let path = entry.into_path();
                if let Ok(file) = File::open(&path) {
                    let reader = BufReader::new(file);
                    if let Ok(manifest) = serde_json::from_reader::<_, ConnectorManifest>(reader) {
                        let app = manifest.id.or(manifest.name).unwrap_or_else(|| "connector".to_string());
                        let desc = if !manifest.summary.is_empty() { manifest.summary } else { manifest.description };

                        for route in manifest.routes {
                            let route_clean = route.split("://").last().unwrap_or("").trim_matches('/');
                            let proc_sub = route_clean.replace('/', "_");
                            let proc_name = format!("{}.{}", app, proc_sub);
                            let uri = format!("proc://{}/{}/v1", app, route_clean);
                            let effect = if route.contains("/command/") { "mutating".to_string() } else { "pure".to_string() };

                            let mut hasher = Sha256::new();
                            hasher.update(uri.as_bytes());
                            hasher.update(desc.as_bytes());
                            hasher.update(effect.as_bytes());
                            let hash_bytes = hasher.finalize();
                            let digest = hash_bytes.iter().map(|b| format!("{:02x}", b)).collect::<String>();

                            procs.push(IndexedProcedure {
                                app: app.clone(),
                                proc_name,
                                uri,
                                desc: format!("[{app}] {desc}"),
                                effect,
                                contract_digest: digest,
                                manifest_path: path.clone(),
                            });
                        }
                    }
                }
            }
        }
    }

    (procs, manifests_found)
}

fn search_nl<'a>(procs: &'a [IndexedProcedure], query: &str) -> Vec<&'a IndexedProcedure> {
    let q = query.to_lowercase();
    let words: Vec<&str> = q.split_whitespace().collect();

    let mut scored: Vec<(usize, &IndexedProcedure)> = procs
        .iter()
        .map(|p| {
            let mut score = 0;
            let corpus = format!("{} {} {}", p.app, p.proc_name, p.desc).to_lowercase();
            for w in &words {
                if p.proc_name.to_lowercase().contains(w) {
                    score += 3;
                }
                if corpus.contains(w) {
                    score += 1;
                }
            }
            (score, p)
        })
        .filter(|(s, _)| *s > 0)
        .collect();

    scored.sort_by(|a, b| b.0.cmp(&a.0));
    scored.into_iter().map(|(_, p)| p).collect()
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let scan_dir = if args.len() > 1 { &args[1] } else { "/home/tom/github/urirun-connectors" };
    let cache_file = PathBuf::from("/tmp/dockuri_fast_cache.json");

    println!("============================================================");
    println!("🦀 DOCKURI-FAST: RUST SCANNER & REGISTRY BENCHMARK");
    println!("   Target root: {}", scan_dir);
    println!("============================================================");

    // 1. Cold Scan
    let t0 = Instant::now();
    let (procs, manifest_count) = scan_directory(scan_dir);
    let dur_cold = t0.elapsed();

    println!("⚡ 1. Cold Scan completed in: {:?} ({} ms)", dur_cold, dur_cold.as_secs_f64() * 1000.0);
    println!("   Manifests found:    {}", manifest_count);
    println!("   Procedures indexed: {}", procs.len());

    // Save to cache
    if let Ok(file) = File::create(&cache_file) {
        let _ = serde_json::to_writer(file, &procs);
    }

    // 2. Warm / Cached Load
    let t_warm = Instant::now();
    let cached_procs: Vec<IndexedProcedure> = if let Ok(file) = File::open(&cache_file) {
        serde_json::from_reader(BufReader::new(file)).unwrap_or_default()
    } else {
        Vec::new()
    };
    let dur_warm = t_warm.elapsed();

    println!("🚀 2. Warm Cache Load completed in: {:?} ({} ms)", dur_warm, dur_warm.as_secs_f64() * 1000.0);
    println!("   Speedup from cache: {:.1}x", dur_cold.as_secs_f64() / dur_warm.as_secs_f64());
    println!("------------------------------------------------------------");

    for p in &cached_procs {
        println!(" • {:<45} [digest: {:.8}...] ({})", p.uri, p.contract_digest, p.manifest_path.display());
    }

    // 3. NL Search
    println!("\n🔍 3. Ultra-Fast NL Search:");
    let q = "base64 encode";
    let t_search = Instant::now();
    let matches = search_nl(&cached_procs, q);
    let s_dur = t_search.elapsed();

    println!("   Query: \"{}\" -> matched {} procs in {:?}", q, matches.len(), s_dur);
    for m in matches {
        println!("    -> {} ({})", m.proc_name, m.desc);
    }
}
