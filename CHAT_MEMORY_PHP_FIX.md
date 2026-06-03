# Fix for chat_memory.php — Undefined constant "WINDOW_SIZE"

Open this file on your server:
  /home2/agbaieke/public_html/chainmind.com.ng/api/chat_memory.php

Find the line that starts with:  <?php

Add these lines IMMEDIATELY after <?php (before any other code):

```php
<?php
// ── Missing constants fix ──────────────────────────────────────
if (!defined('WINDOW_SIZE'))    define('WINDOW_SIZE',    20);
if (!defined('MAX_TOKENS'))     define('MAX_TOKENS',  4096);
if (!defined('SUMMARY_EVERY'))  define('SUMMARY_EVERY',  10);
// ──────────────────────────────────────────────────────────────
```

Save the file. The PHP errors will stop immediately — no server restart needed.
