<?php
// ============================================================
// ChainMind Central  Shared helpers
// ============================================================

require_once __DIR__ . '/../config.php';

//    PDO connection (singleton)
function db(): PDO {
    static $pdo = null;
    if ($pdo === null) {
        $dsn = "mysql:host=" . DB_HOST . ";dbname=" . DB_NAME . ";charset=" . DB_CHARSET;
        $pdo = new PDO($dsn, DB_USER, DB_PASS, [
            PDO::ATTR_ERRMODE            => PDO::ERRMODE_EXCEPTION,
            PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
            PDO::ATTR_EMULATE_PREPARES   => false,
        ]);
    }
    return $pdo;
}

//    CORS
function cors(): void {
    $origin = $_SERVER['HTTP_ORIGIN'] ?? '';
    if (in_array($origin, ALLOWED_ORIGINS, true)) {
        header("Access-Control-Allow-Origin: $origin");
    }
    header('Access-Control-Allow-Methods: GET, POST, DELETE, OPTIONS');
    header('Access-Control-Allow-Headers: Content-Type, X-Api-Key, X-Node-Secret, X-Node-Id');
    header('Access-Control-Max-Age: 86400');
    if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') { http_response_code(204); exit; }
}

//    JSON response helpers
function json_ok(array $data, int $code = 200): void {
    http_response_code($code);
    header('Content-Type: application/json');
    echo json_encode($data, JSON_UNESCAPED_UNICODE);
    exit;
}

function json_err(string $message, int $code = 400): void {
    http_response_code($code);
    header('Content-Type: application/json');
    echo json_encode(['error' => $message]);
    exit;
}

//    Input helpers
function body(): array {
    $raw = file_get_contents('php://input');
    return json_decode($raw, true) ?? [];
}

function require_json_body(): array {
    $b = body();
    if (empty($b)) json_err('Request body must be valid JSON', 400);
    return $b;
}

//    Auth helpers
function validate_api_key(): array {
    $key = $_SERVER['HTTP_X_API_KEY'] ?? ($_GET['api_key'] ?? '');
    if (!$key) json_err('Missing API key. Send X-Api-Key header.', 401);

    $stmt = db()->prepare('SELECT * FROM api_keys WHERE api_key = ? AND is_active = 1');
    $stmt->execute([$key]);
    $row = $stmt->fetch();
    if (!$row) json_err('Invalid or inactive API key.', 403);

    db()->prepare('UPDATE api_keys SET last_used = NOW() WHERE id = ?')->execute([$row['id']]);
    return $row;
}

function validate_node_secret(): void {
    // Validate per-node secret against the database.
    // The global NODE_SECRET constant is no longer used for node auth.
    $node_id = $_SERVER['HTTP_X_NODE_ID'] ?? '';
    $secret  = $_SERVER['HTTP_X_NODE_SECRET'] ?? '';

    if (!$node_id) json_err('Missing X-Node-Id header.', 400);
    if (!$secret)  json_err('Missing X-Node-Secret header.', 400);

    $stmt = db()->prepare('SELECT secret FROM nodes WHERE id = ? LIMIT 1');
    $stmt->execute([$node_id]);
    $row = $stmt->fetch();

    if (!$row || !hash_equals((string)$row['secret'], $secret)) {
        json_err('Invalid node secret.', 403);
    }
}

function get_node_id(): string {
    $id = $_SERVER['HTTP_X_NODE_ID'] ?? '';
    if (!$id) json_err('Missing X-Node-Id header.', 400);
    return $id;
}

//    Encryption helpers
function encrypt_field(?string $text): string {
    if (!$text || !defined('ENCRYPTION_KEY') || !ENCRYPTION_KEY) return (string)$text;
    $iv         = random_bytes(16);
    $ciphertext = openssl_encrypt($text, 'AES-256-CBC', ENCRYPTION_KEY, OPENSSL_RAW_DATA, $iv);
    return 'enc:' . base64_encode($iv . $ciphertext);
}

function decrypt_field(?string $text): string {
    if (!$text || !defined('ENCRYPTION_KEY') || !ENCRYPTION_KEY) return (string)$text;
    if (strncmp($text, 'enc:', 4) !== 0) return (string)$text;
    $decoded    = base64_decode(substr($text, 4));
    $iv         = substr($decoded, 0, 16);
    $ciphertext = substr($decoded, 16);
    $plain      = openssl_decrypt($ciphertext, 'AES-256-CBC', ENCRYPTION_KEY, OPENSSL_RAW_DATA, $iv);
    return $plain !== false ? $plain : (string)$text;
}

//    UUID generator
function uuid4(): string {
    return sprintf('%04x%04x-%04x-%04x-%04x-%04x%04x%04x',
        mt_rand(0, 0xffff), mt_rand(0, 0xffff),
        mt_rand(0, 0xffff),
        mt_rand(0, 0x0fff) | 0x4000,
        mt_rand(0, 0x3fff) | 0x8000,
        mt_rand(0, 0xffff), mt_rand(0, 0xffff), mt_rand(0, 0xffff)
    );
}

// ── Safe schema migration (MySQL 8.x compatible) ───────────────────────────
// MySQL 8.x does NOT support "ADD COLUMN IF NOT EXISTS" (that's MariaDB only).
// Use SHOW COLUMNS to check before each ALTER TABLE.
function ensure_jobs_columns(): void {
    static $done = false;
    if ($done) return;   // only run once per request
    $done = true;

    $needed = [
        'job_type'      => "ALTER TABLE jobs ADD COLUMN job_type VARCHAR(20) NOT NULL DEFAULT 'text'",
        'image_params'  => "ALTER TABLE jobs ADD COLUMN image_params JSON NULL",
        'file_ids'      => "ALTER TABLE jobs ADD COLUMN file_ids JSON NULL",
        'result_images' => "ALTER TABLE jobs ADD COLUMN result_images JSON NULL",
        'user_id'       => "ALTER TABLE jobs ADD COLUMN user_id INT NULL",
        'api_key_id'    => "ALTER TABLE jobs ADD COLUMN api_key_id INT NULL",
        'source'        => "ALTER TABLE jobs ADD COLUMN source VARCHAR(50) NULL DEFAULT 'api'",
    ];

    foreach ($needed as $col => $ddl) {
        try {
            // Use INFORMATION_SCHEMA instead of SHOW COLUMNS LIKE ? (placeholder not supported in all MySQL versions)
            $safeCol = preg_replace('/[^a-zA-Z0-9_]/', '', $col); // sanitize column name
            $q = db()->query("SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'jobs' AND COLUMN_NAME = '{$safeCol}'");
            if ((int)$q->fetchColumn() === 0) {
                db()->exec($ddl);
                error_log("[schema] Added column: {$col}");
            }
        } catch (\Throwable $e) {
            error_log("[schema] Could not check/add column {$col}: " . $e->getMessage());
        }
    }
}

// ── Model routing: detect an explicit model request inside a chat prompt ──
// Recognises phrases like "use llama3.1:70b", "answer with mistral",
// "respond using qwen2", "can you use deepseek for this", etc.
// Returns the canonical model id (matching nodes.models / api/v1/models.php)
// or null if the user didn't ask for a specific model.
function detect_requested_model(string $prompt): ?string {
    $known_models = [
        'mistral'          => ['mistral'],
        'llama3.1:70b'     => ['llama3.1:70b', 'llama 3.1 70b', 'llama3.1 70b', 'llama 70b'],
        'llama3.1:8b'      => ['llama3.1:8b', 'llama 3.1 8b', 'llama3.1 8b', 'llama3', 'llama 3', 'llama'],
        'llama3.2:3b'      => ['llama3.2:3b', 'llama 3.2 3b', 'llama3.2 3b'],
        'llama3.2:1b'      => ['llama3.2:1b', 'llama 3.2 1b', 'llama3.2 1b'],
        'gemma2:9b'        => ['gemma2:9b', 'gemma 2 9b', 'gemma2 9b', 'gemma2', 'gemma'],
        'gemma2:2b'        => ['gemma2:2b', 'gemma 2 2b', 'gemma2 2b'],
        'mixtral:8x7b'     => ['mixtral:8x7b', 'mixtral 8x7b', 'mixtral'],
        'qwen2:72b'        => ['qwen2:72b', 'qwen2 72b', 'qwen 72b', 'qwen2', 'qwen'],
        'deepseek-r1:7b'   => ['deepseek-r1:7b', 'deepseek r1', 'deepseek-r1', 'deepseek'],
        'phi3:mini'        => ['phi3:mini', 'phi-3', 'phi3', 'phi 3'],
        'tinyllama'        => ['tinyllama', 'tiny llama'],
        'qwen2:0.5b'       => ['qwen2:0.5b', 'qwen2 0.5b', 'qwen 0.5b'],
    ];

    $p = strtolower($prompt);

    // Only look at requests that actually sound like a model instruction,
    // to avoid false positives on prompts that merely mention a model name
    // in passing (e.g. "what is mistral wind").
    $trigger = '/\b(use|using|with|via|switch to|answer|respond|reply)\b.{0,30}\b(model|llama|mistral|qwen|gemma|deepseek|phi|mixtral|tinyllama)\b/i';
    if (!preg_match($trigger, $p) && !preg_match('/\bmodel\s*[:=]\s*[\w.:\-]+/i', $p)) {
        return null;
    }

    foreach ($known_models as $id => $aliases) {
        foreach ($aliases as $alias) {
            if (str_contains($p, $alias)) {
                return $id;
            }
        }
    }
    return null;
}

// ── Which models are actually available right now (online nodes only) ────
function get_online_models(): array {
    sweep_offline_nodes();
    $rows = db()->query("SELECT models FROM nodes WHERE status = 'online' AND models IS NOT NULL")->fetchAll();
    $available = [];
    foreach ($rows as $r) {
        $list = json_decode($r['models'] ?? '[]', true);
        if (is_array($list)) {
            foreach ($list as $m) {
                $m = trim((string)$m);
                if ($m !== '') $available[$m] = true;
            }
        }
    }
    return array_keys($available);
}

// ── Resolve a requested model against what's actually online ──────────────
// Returns ['model' => string|null, 'note' => string|null]
//   model: the model id to actually use (null = let any node pick up the job)
//   note:  a human-readable message to show the user about routing
function resolve_model_request(string $prompt): array {
    $requested = detect_requested_model($prompt);
    if (!$requested) {
        return ['model' => null, 'note' => null];
    }

    $online = get_online_models();

    if (in_array($requested, $online, true)) {
        return [
            'model' => $requested,
            'note'  => "Using {$requested} as requested.",
        ];
    }

    // Requested model isn't online right now — fall back to auto-routing
    // and tell the user what happened.
    if (empty($online)) {
        return [
            'model' => null,
            'note'  => "{$requested} isn't available right now, and no nodes are currently online. Your message will be routed to the next node that comes online.",
        ];
    }

    return [
        'model' => null,
        'note'  => "{$requested} isn't available right now — routing you to the next available model instead.",
    ];
}

//    Mark timed-out jobs
function sweep_timeouts(): void {
    db()->exec("
        UPDATE jobs
        SET status = 'timeout', finished_at = NOW()
        WHERE status IN ('pending','claimed')
          AND created_at < NOW() - INTERVAL " . JOB_POLL_TIMEOUT . " SECOND
    ");
}

//    Mark nodes offline if no heartbeat
function sweep_offline_nodes(): void {
    $sql = "
        UPDATE nodes
        SET status = 'offline'
        WHERE last_seen < NOW() - INTERVAL " . NODE_OFFLINE_SECONDS . " SECOND
          AND status != 'offline'
    ";
    $maxRetries = 3;
    for ($attempt = 1; $attempt <= $maxRetries; $attempt++) {
        try {
            db()->exec($sql);
            return;
        } catch (\PDOException $e) {
            if ($e->getCode() === '40001' && $attempt < $maxRetries) {
                usleep(100000 * $attempt);
                continue;
            }
            error_log('[sweep_offline_nodes] ' . $e->getMessage());
            return;
        }
    }
}

// ── Google OAuth config (reads from .htaccess SetEnv or cPanel env vars) ──
function google_oauth_config(): array {
    $id     = getenv('GOOGLE_CLIENT_ID');
    $secret = getenv('GOOGLE_CLIENT_SECRET');

    if (!$id || !$secret) {
        error_log('[Google OAuth] Env vars missing — check cPanel PHP environment settings');
        return [];
    }
    return [
        'client_id'     => $id,
        'client_secret' => $secret,
        'redirect_uri'  => 'https://chainmind.com.ng/auth/google-callback.php',
        'token_url'     => 'https://oauth2.googleapis.com/token',
        'userinfo_url'  => 'https://www.googleapis.com/oauth2/v3/userinfo',
    ];
}

// ── Token exchange using curl (file_get_contents may be blocked) ──────────
function google_exchange_code(string $code): ?array {
    $cfg = google_oauth_config();
    if (!$cfg) return null;

    $ch = curl_init($cfg['token_url']);
    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_POST           => true,
        CURLOPT_POSTFIELDS     => http_build_query([
            'code'          => $code,
            'client_id'     => $cfg['client_id'],
            'client_secret' => $cfg['client_secret'],
            'redirect_uri'  => $cfg['redirect_uri'],
            'grant_type'    => 'authorization_code',
        ]),
        CURLOPT_HTTPHEADER     => ['Content-Type: application/x-www-form-urlencoded'],
        CURLOPT_TIMEOUT        => 15,
        CURLOPT_SSL_VERIFYPEER => true,
    ]);

    $body = curl_exec($ch);
    $err  = curl_error($ch);
    $http = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);

    if ($err || $http !== 200) {
        error_log("[Google OAuth] Token exchange failed: curl_err={$err} http={$http} body={$body}");
        return null;
    }

    return json_decode($body, true);
}

// ── Fetch Google user info from access token ──────────────────────────────
function google_get_userinfo(string $access_token): ?array {
    $cfg = google_oauth_config();
    if (!$cfg) return null;

    $ch = curl_init($cfg['userinfo_url']);
    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_HTTPHEADER     => ["Authorization: Bearer {$access_token}"],
        CURLOPT_TIMEOUT        => 10,
        CURLOPT_SSL_VERIFYPEER => true,
    ]);

    $body = curl_exec($ch);
    $err  = curl_error($ch);
    curl_close($ch);

    if ($err) {
        error_log("[Google OAuth] Userinfo fetch failed: {$err}");
        return null;
    }

    return json_decode($body, true);
}


// ── Email helper ───────────────────────────────────────────────────────────────
/**
 * Send a professional HTML email via PHP mail() with proper headers for Gmail.
 *
 * On cPanel, mail() routes through the server's Exim MTA which handles
 * SPF signing automatically when sending from a domain hosted on the same server.
 *
 * Tips for Gmail deliverability:
 *  1. Make sure chainmind.com.ng has an SPF record in DNS:
 *     v=spf1 a mx include:chainmind.com.ng ~all
 *  2. Enable DKIM in cPanel -> Email -> Authentication
 *  3. Set up DMARC:  _dmarc.chainmind.com.ng  TXT  "v=DMARC1; p=none"
 *
 * Falls back gracefully if mail() fails: logs the error and returns false.
 */
function send_email(string $to, string $subject, string $html, string $text = ''): bool {
    $from_name  = 'ChainMind';
    $from_email = 'noreply@chainmind.com.ng';

    // Build plain-text fallback from HTML
    if (!$text) {
        $text = html_entity_decode(
            strip_tags(preg_replace('#<br\s*/?>|</p>|</div>|</li>#i', "\n", $html)),
            ENT_QUOTES | ENT_HTML5,
            'UTF-8'
        );
        $text = preg_replace("/[ \t]+/", ' ', $text);
        $text = preg_replace("/\n{3,}/", "\n\n", trim($text));
    }

    $boundary  = 'mp_' . md5(uniqid('', true));
    $msg_id    = '<' . bin2hex(random_bytes(12)) . '@chainmind.com.ng>';
    $date      = date('r'); // RFC 2822 date

    // Encode subject for non-ASCII safety
    $enc_subject = '=?UTF-8?B?' . base64_encode($subject) . '?=';

    // Encode From name
    $enc_from = '=?UTF-8?B?' . base64_encode($from_name) . '?= <' . $from_email . '>';

    $headers  = "From: {$enc_from}\r\n";
    $headers .= "Reply-To: {$from_email}\r\n";
    $headers .= "Return-Path: <{$from_email}>\r\n";
    $headers .= "Message-ID: {$msg_id}\r\n";
    $headers .= "Date: {$date}\r\n";
    $headers .= "MIME-Version: 1.0\r\n";
    $headers .= "Content-Type: multipart/alternative; boundary=\"{$boundary}\"\r\n";
    $headers .= "X-Mailer: ChainMind-Mailer/2.0\r\n";
    $headers .= "X-Priority: 3\r\n";
    $headers .= "List-Unsubscribe: <mailto:unsubscribe@chainmind.com.ng?subject=unsubscribe>\r\n";
    $headers .= "Precedence: bulk\r\n";

    // Quoted-printable encode HTML for best compatibility
    $html_qp = quoted_printable_encode($html);
    // Plain text — wrap at 72 chars
    $text_wrapped = wordwrap($text, 72, "\r\n", false);

    $body  = "--{$boundary}\r\n";
    $body .= "Content-Type: text/plain; charset=UTF-8\r\n";
    $body .= "Content-Transfer-Encoding: quoted-printable\r\n\r\n";
    $body .= quoted_printable_encode($text_wrapped) . "\r\n\r\n";
    $body .= "--{$boundary}\r\n";
    $body .= "Content-Type: text/html; charset=UTF-8\r\n";
    $body .= "Content-Transfer-Encoding: quoted-printable\r\n\r\n";
    $body .= $html_qp . "\r\n\r\n";
    $body .= "--{$boundary}--";

    // -f flag sets the envelope sender (Return-Path) — important for spam scoring
    $ok = @mail($to, $enc_subject, $body, $headers, "-f{$from_email}");

    if (!$ok) {
        error_log("[send_email] mail() failed: to={$to}, subject={$subject}");
    }

    return $ok;
}

/**
 * Build a consistent, professional ChainMind HTML email wrapper.
 * Compatible with Gmail, Outlook, Apple Mail, and mobile clients.
 */
function email_html(string $title, string $body_html): string {
    $safe_title = htmlspecialchars($title, ENT_QUOTES | ENT_HTML5);
    return <<<HTML
<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="X-UA-Compatible" content="IE=edge">
<title>{$safe_title}</title>
<!--[if mso]>
<style>table{border-collapse:collapse}td,th{font-family:Arial,sans-serif}</style>
<![endif]-->
</head>
<body style="margin:0;padding:0;background-color:#0a0c10;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%">

<table width="100%" cellpadding="0" cellspacing="0" border="0" role="presentation"
  style="background-color:#0a0c10;padding:32px 16px">
<tr><td align="center">

  <!-- Outer card -->
  <table width="560" cellpadding="0" cellspacing="0" border="0" role="presentation"
    style="max-width:560px;width:100%;background-color:#161b22;border:1px solid #30363d;
           border-radius:12px;overflow:hidden">

    <!-- Header / Logo -->
    <tr>
      <td style="padding:24px 32px;border-bottom:1px solid #21262d;text-align:center;
                 background-color:#0d1117">
        <span style="font-size:22px;font-weight:800;color:#e6edf3;text-decoration:none;
                     letter-spacing:-.3px">
          <span style="color:#58a6ff">Chain</span>Mind
        </span>
      </td>
    </tr>

    <!-- Body -->
    <tr>
      <td style="padding:32px 40px;color:#e6edf3;font-size:15px;line-height:1.6">
        {$body_html}
      </td>
    </tr>

    <!-- Footer -->
    <tr>
      <td style="padding:20px 40px;border-top:1px solid #21262d;text-align:center;
                 background-color:#0d1117">
        <p style="margin:0 0 6px;font-size:12px;color:#8b949e">
          &copy; 2026 ChainMind &mdash; Decentralised AI Network
        </p>
        <p style="margin:0;font-size:12px;color:#8b949e">
          <a href="https://chainmind.com.ng" style="color:#58a6ff;text-decoration:none">chainmind.com.ng</a>
          &nbsp;&bull;&nbsp;
          <a href="mailto:support@chainmind.com.ng" style="color:#58a6ff;text-decoration:none">support@chainmind.com.ng</a>
        </p>
        <p style="margin:8px 0 0;font-size:11px;color:#6e7681">
          You received this email because you registered at ChainMind.<br>
          <a href="mailto:unsubscribe@chainmind.com.ng?subject=unsubscribe" style="color:#6e7681">Unsubscribe</a>
        </p>
      </td>
    </tr>

  </table>
</td></tr>
</table>

</body>
</html>
HTML;
}
