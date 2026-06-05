<?php
/**
 * /api/node/pair.php
 * ChainMind Node Pairing Endpoint
 *
 * Called by the node app's setup wizard and the dashboard "Reconnect"
 * button when a user wants to pair/re-pair this node to their web account
 * using a short-lived pairing token generated on the web dashboard.
 *
 * POST /api/node/pair.php
 * Body (JSON): { "token": "<48-hex-char pairing token>" }
 *
 * Returns:
 *   Success: { "ok": true, "node_secret": "...", "node_id": "...", "username": "..." }
 *   Error:   { "ok": false, "error": "..." }
 *
 * Required DB table (create this if it doesn't exist):
 *
 *   CREATE TABLE pairing_tokens (
 *       id         INT AUTO_INCREMENT PRIMARY KEY,
 *       token      VARCHAR(64)  NOT NULL UNIQUE,
 *       user_id    INT          NOT NULL,
 *       expires_at DATETIME     NOT NULL,
 *       used_at    DATETIME     NULL,
 *       INDEX idx_token (token)
 *   );
 *
 * Your node-settings.php page should generate tokens like this:
 *   $token = bin2hex(random_bytes(24));   // 48-char hex
 *   INSERT INTO pairing_tokens (token, user_id, expires_at)
 *   VALUES (:token, :user_id, DATE_ADD(NOW(), INTERVAL 10 MINUTE));
 */

declare(strict_types=1);

$config_path = dirname(__DIR__, 2) . '/config.php';
if (file_exists($config_path)) {
    require_once $config_path;
}

function db_connect(): PDO
{
    static $pdo = null;
    if ($pdo !== null) return $pdo;

    $host    = defined('DB_HOST') ? DB_HOST : (getenv('DB_HOST') ?: 'localhost');
    $name    = defined('DB_NAME') ? DB_NAME : (getenv('DB_NAME') ?: 'agbaieke_chainmind');
    $user    = defined('DB_USER') ? DB_USER : (getenv('DB_USER') ?: '');
    $pass    = defined('DB_PASS') ? DB_PASS : (getenv('DB_PASS') ?: '');

    $pdo = new PDO("mysql:host={$host};dbname={$name};charset=utf8mb4", $user, $pass, [
        PDO::ATTR_ERRMODE            => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        PDO::ATTR_EMULATE_PREPARES   => false,
    ]);
    return $pdo;
}

function json_out(array $data, int $status = 200): never
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    header('X-Content-Type-Options: nosniff');
    header('Access-Control-Allow-Origin: *');
    echo json_encode($data, JSON_UNESCAPED_UNICODE);
    exit;
}

function generate_uuid(): string
{
    $bytes    = random_bytes(16);
    $bytes[6] = chr((ord($bytes[6]) & 0x0f) | 0x40);
    $bytes[8] = chr((ord($bytes[8]) & 0x3f) | 0x80);
    return vsprintf('%s%s-%s-%s-%s-%s%s%s', str_split(bin2hex($bytes), 4));
}

// CORS preflight
if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') {
    header('Access-Control-Allow-Methods: POST, OPTIONS');
    header('Access-Control-Allow-Headers: Content-Type');
    http_response_code(204);
    exit;
}

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    json_out(['ok' => false, 'error' => 'Method not allowed.'], 405);
}

$body = json_decode(file_get_contents('php://input'), true);
if (!is_array($body)) {
    json_out(['ok' => false, 'error' => 'Invalid JSON body.'], 400);
}

$token = trim((string)($body['token'] ?? ''));
if ($token === '') {
    json_out(['ok' => false, 'error' => 'token is required.'], 400);
}
if (!preg_match('/^[0-9a-f]{32,128}$/i', $token)) {
    json_out(['ok' => false, 'error' => 'Invalid token format.'], 400);
}

try {
    $db = db_connect();

    // ── 1. Validate pairing token ─────────────────────────────────────────────
    $stmt = $db->prepare('
        SELECT pt.id, pt.user_id, pt.expires_at, pt.used_at,
               u.name, u.email, u.is_active, u.email_verified
        FROM pairing_tokens pt
        JOIN users u ON u.id = pt.user_id
        WHERE pt.token = :token
        LIMIT 1
    ');
    $stmt->execute([':token' => $token]);
    $row = $stmt->fetch();

    if (!$row) {
        json_out(['ok' => false, 'error' => 'Invalid or expired pairing token.'], 401);
    }
    if ($row['used_at'] !== null) {
        json_out(['ok' => false, 'error' => 'This pairing token has already been used. Generate a new one from the web dashboard.'], 401);
    }
    if (strtotime($row['expires_at']) < time()) {
        json_out(['ok' => false, 'error' => 'Pairing token has expired. Generate a new one from the web dashboard.'], 401);
    }
    if (!(int)$row['is_active']) {
        json_out(['ok' => false, 'error' => 'Account is disabled. Contact support.'], 403);
    }
    if (!(int)$row['email_verified']) {
        json_out(['ok' => false, 'error' => 'Please verify your email address before connecting a node.'], 403);
    }

    $user_id  = (int)$row['user_id'];
    $username = (string)$row['name'];
    $email    = (string)$row['email'];

    // ── 2. Mark token as used ─────────────────────────────────────────────────
    $db->prepare('UPDATE pairing_tokens SET used_at = NOW() WHERE id = :id')
       ->execute([':id' => $row['id']]);

    // ── 3. Find or create node for this user ──────────────────────────────────
    $stmt = $db->prepare('
        SELECT id, secret
        FROM nodes
        WHERE user_id = :uid
        ORDER BY registered_at DESC
        LIMIT 1
    ');
    $stmt->execute([':uid' => $user_id]);
    $existing_node = $stmt->fetch();

    if ($existing_node && !empty($existing_node['secret'])) {
        // Existing node — reuse secret, refresh last_seen
        $node_id     = $existing_node['id'];
        $node_secret = $existing_node['secret'];

        $db->prepare('UPDATE nodes SET last_seen = NOW(), status = "online" WHERE id = :nid')
           ->execute([':nid' => $node_id]);

    } elseif ($existing_node) {
        // Node exists but no secret yet
        $node_id     = $existing_node['id'];
        $node_secret = bin2hex(random_bytes(32));

        $db->prepare('
            UPDATE nodes
            SET secret = :secret, user_id = :uid, linked_at = NOW(),
                linked_email = :email, last_seen = NOW(), status = "online"
            WHERE id = :nid
        ')->execute([
            ':secret' => $node_secret, ':uid' => $user_id,
            ':email'  => $email,       ':nid' => $node_id,
        ]);

    } else {
        // New node
        $node_id     = generate_uuid();
        $node_secret = bin2hex(random_bytes(32));

        $db->prepare('
            INSERT INTO nodes
                (id, name, secret, user_id, linked_at, linked_email, url, tier, status, last_seen, registered_at)
            VALUES
                (:id, :name, :secret, :uid, NOW(), :email, "", "nano", "online", NOW(), NOW())
        ')->execute([
            ':id'     => $node_id,
            ':name'   => $username . "'s Node",
            ':secret' => $node_secret,
            ':uid'    => $user_id,
            ':email'  => $email,
        ]);

        $db->prepare('UPDATE users SET role = "node" WHERE id = :uid AND role = "user"')
           ->execute([':uid' => $user_id]);
    }

    json_out([
        'ok'          => true,
        'node_secret' => $node_secret,
        'node_id'     => $node_id,
        'username'    => $username,
    ]);

} catch (PDOException $e) {
    error_log('ChainMind pair.php DB error: ' . $e->getMessage());
    json_out(['ok' => false, 'error' => 'Server error. Please try again later.'], 500);
}
