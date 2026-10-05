<?php
/**
 * Reference PHP Worker Daemon for Dockuri (DOCK-STD-001).
 * Listens on Unix Domain Socket, executes procedures with zero cold-start.
 */

declare(strict_types=1);

$socketPath = getenv('DOCKURI_SOCKET') ?: '/tmp/dockuri_php_ref.sock';

if (file_exists($socketPath)) {
    unlink($socketPath);
}

$server = stream_socket_server("unix://$socketPath", $errno, $errstr);
if (!$server) {
    fwrite(STDERR, "Error creating socket: $errstr ($errno)\n");
    exit(1);
}
chmod($socketPath, 0660);
echo "✓ Dockuri PHP Worker ready on UDS: $socketPath (PID " . getmypid() . ")\n";

$registry = [
    'codec.base64_encode' => fn($args) => base64_encode((string)($args['text'] ?? '')),
    'codec.base64_decode' => fn($args) => base64_decode((string)($args['text'] ?? ''), true),
];

while ($conn = @stream_socket_accept($server, -1)) {
    while ($line = fgets($conn)) {
        $t0 = microtime(true);
        $req = json_decode(trim($line), true);
        if (!$req) continue;

        $id = $req['id'] ?? 'unknown';
        $proc = $req['proc'] ?? '';
        $args = $req['args'] ?? [];
        $result = null;
        $error = null;

        if ($proc === '__ping__') {
            $result = ['status' => 'pong', 'runtime' => 'php-' . PHP_VERSION, 'pid' => getmypid()];
        } elseif (isset($registry[$proc])) {
            try {
                $result = $registry[$proc]($args);
            } catch (Throwable $e) {
                $error = $e->getMessage();
            }
        } else {
            $error = "Procedure not found: $proc";
        }

        $durationUs = (int)((microtime(true) - $t0) * 1000000);
        $resp = [
            'id' => $id,
            'ok' => $error === null,
            'result' => $result,
            'error' => $error,
            'metrics' => ['duration_us' => $durationUs],
        ];
        fwrite($conn, json_encode($resp) . "\n");
    }
    fclose($conn);
}
