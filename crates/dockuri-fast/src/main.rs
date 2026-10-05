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

fn is_excluded(entry: &DirEntry) -> bool {
    if entry.file_type().is_dir() {
        let name = entry.file_name().to_string_lossy();
        if EXCLUDED.iter().any(|&ex| ex == name) {
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
        if entry.file_name() == "dockuri.json" && entry.file_type().is_file() {
            manifests_found += 1;
            let path = entry.into_path();
            if let Ok(file) = File::open(&path) {
                let reader = BufReader::new(file);
                if let Ok(manifest) = serde_json::from_reader::<_, Manifest>(reader) {
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
