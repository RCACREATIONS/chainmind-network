<?php
/**
 * /api/node/register.php
 * ChainMind Node Registration Endpoint
 *
 * Called by the node app's setup wizard when a user wants to
 * connect their node to the ChainMind network.
 *
 * POST /api/node/register.php
 * Body (JSON): { "email": "...", "password": "...", "node_name": "..." }
 *
 * Returns:
 *   Success: { "ok": true, "node_secret": "...", "node_id": "...", "username": "..." }
 *   Error:   { "ok": false, "error": "..." }
 *
 * Works with the existing agbaieke_chainmind database.
 * Uses the `nodes` table (id, name, secret, user_id, linked_email, linked_at,
 *   url, tier, status, last_seen, registered_at)
 * and the `users` table (id, email, password_hash, name, is_active, email_verified).
 */

declare(strict_types=1);

// ── Load shared config (DB credentials live in config.php via env vars) ───────
$config_path = dirname(__DIR__, 2) . '/config.php';
if (file_exists($config_path)) {
    require_once $config_path;
}

// Fallback: read directly from environment variables if config.php not found
function db_connect(): PDO
{
    static $pdo = null;
    if ($pdo !== null) return $pdo;

    $host    = defined('DB_HOST') ? DB_HOST : (getenv('DB_HOST') ?: 'localhost');
    $name    = defined('DB_NAME') ? DB_NAME : (getenv('DB_NAME') ?: 'agbaieke_chainmind');
    $user    = defined('DB_USER') ? DB_USER : (getenv('DB_USER') ?: '');
    $pass    = defined('DB_PASS') ? DB_PASS : (getenv('DB_PASS') ?: '');
    $charset = 'utf8mb4';

    $dsn = "mysql:host={$host};dbname={$name};charset={$charset}";
    $pdo = new PDO($dsn, $user, $pass, [
        PDO::ATTR_ERRMODE            => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        PDO::ATTR_EMULATE_PREPARES   => false,
    ]);
    return $pdo;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

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

// ── CORS preflight ─────────────────────────────────────────────────────────────
if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') {
    header('Access-Control-Allow-Methods: POST, OPTIONS');
    header('Access-Control-Allow-Headers: Content-Type');
    http_response_code(204);
    exit;
}

// ── Only POST allowed ──────────────────────────────────────────────────────────
if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    json_out(['ok' => false, 'error' => 'Method not allowed.'], 405);
}

// ── Parse body ────────────────────────────────────────────────────────────────
$body = json_decode(file_get_contents('php://input'), true);
if (!is_array($body)) {
    json_out(['ok' => false, 'error' => 'Invalid JSON body.'], 400);
}

$email     = trim((string)($body['email']     ?? ''));
$password  = (string)($body['password']  ?? '');
$node_name = trim((string)($body['node_name'] ?? ''));

if ($email === '' || $password === '') {
    json_out(['ok' => false, 'error' => 'email and password are required.'], 400);
}

if (!filter_var($email, FILTER_VALIDATE_EMAIL)) {
    json_out(['ok' => false, 'error' => 'Invalid email address.'], 400);
}

// ── Main ──────────────────────────────────────────────────────────────────────
try {
    $db = db_connect();

    // ── 1. Look up user ───────────────────────────────────────────────────────
    $stmt = $db->prepare('
        SELECT id, name, password_hash, is_active, email_verified
        FROM users
        WHERE email = :email
        LIMIT 1
    ');
    $stmt->execute([':email' => $email]);
    $user = $stmt->fetch();

    if (!$user || !password_verify($password, $user['password_hash'])) {
        json_out(['ok' => false, 'error' => 'Invalid email or password.'], 401);
    }

    if (!(int)$user['is_active']) {
        json_out(['ok' => false, 'error' => 'Account is disabled. Contact support.'], 403);
    }

    if (!(int)$user['email_verified']) {
        json_out(['ok' => false, 'error' => 'Please verify your email address before connecting a node.'], 403);
    }

    $user_id  = (int)$user['id'];
    $username = (string)$user['name'];

    // ── 2. Check if this user already has a node registered ───────────────────
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
        // Existing node — reuse secret, update last_seen
        $node_id     = $existing_node['id'];
        $node_secret = $existing_node['secret'];

        $db->prepare('UPDATE nodes SET last_seen = NOW(), status = "online" WHERE id = :nid')
           ->execute([':nid' => $node_id]);

    } elseif ($existing_node) {
        // Node exists but has no secret (auto-registered by heartbeat before linking)
        $node_id     = $existing_node['id'];
        $node_secret = bin2hex(random_bytes(32));

        $db->prepare('
            UPDATE nodes
            SET secret       = :secret,
                user_id      = :uid,
                linked_at    = NOW(),
                linked_email = :email,
                last_seen    = NOW(),
                status       = "online"
            WHERE id = :nid
        ')->execute([
            ':secret' => $node_secret,
            ':uid'    => $user_id,
            ':email'  => $email,
            ':nid'    => $node_id,
        ]);

    } else {
        // ── 3. New node — create it ───────────────────────────────────────────
        $node_id     = generate_uuid();
        $node_secret = bin2hex(random_bytes(32));

        if ($node_name === '') {
            $node_name = $username . "'s Node";
        }

        $db->prepare('
            INSERT INTO nodes
                (id, name, secret, user_id, linked_at, linked_email, url, tier, status, last_seen, registered_at)
            VALUES
                (:id, :name, :secret, :uid, NOW(), :email, "", "nano", "online", NOW(), NOW())
        ')->execute([
            ':id'     => $node_id,
            ':name'   => $node_name,
            ':secret' => $node_secret,
            ':uid'    => $user_id,
            ':email'  => $email,
        ]);

        // Upgrade user role to "node" (never downgrade admins)
        $db->prepare('
            UPDATE users SET role = "node"
            WHERE id = :uid AND role = "user"
        ')->execute([':uid' => $user_id]);
    }

    // ── 4. Return credentials to the node app ─────────────────────────────────
    json_out([
        'ok'          => true,
        'node_secret' => $node_secret,
        'node_id'     => $node_id,
        'username'    => $username,
    ]);

} catch (PDOException $e) {
    error_log('ChainMind register.php DB error: ' . $e->getMessage());
    json_out(['ok' => false, 'error' => 'Server error. Please try again later.'], 500);
}
