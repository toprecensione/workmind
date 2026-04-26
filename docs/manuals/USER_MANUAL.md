# WorkMind v2 — User Manual

**Audience:** End users (non-technical)
**Version:** 2.0.0

---

## Welcome to WorkMind

WorkMind is your AI-powered business assistant. It helps you:

- Have natural conversations with an AI that knows your company's documents
- Quickly find information across your knowledge base
- Get notifications via Telegram or WhatsApp
- (For MEDIC users) Manage products, lots, sales, and agent inventory

This manual walks you through the everyday use of WorkMind.

---

## Table of Contents

1. [Logging In](#1-logging-in)
2. [Setting Up Two-Factor Authentication](#2-setting-up-two-factor-authentication)
3. [Forgot Your Password?](#3-forgot-your-password)
4. [Using the Chat](#4-using-the-chat)
5. [Knowledge Base Search](#5-knowledge-base-search)
6. [Conversations Management](#6-conversations-management)
7. [Updating Your Profile](#7-updating-your-profile)
8. [Mobile Use](#8-mobile-use)
9. [MEDIC Features](#9-medic-features)
10. [Frequently Asked Questions](#10-frequently-asked-questions)

---

## 1. Logging In

1. Open the URL provided by your administrator (e.g., `https://workmind-bender.tail898ef4.ts.net`)
2. Enter your email and password
3. Click **Accedi**

If 2FA is enabled, you'll be asked for a 6-digit code from your authenticator app after entering your password.

After logging in, you land on the chat page.

---

## 2. Setting Up Two-Factor Authentication

For better security, enable 2FA:

1. Click on your name in the bottom-left of the sidebar → **Profilo**
2. Go to **Sicurezza** → **Abilita 2FA**
3. Open your authenticator app (Google Authenticator, Authy, 1Password, Bitwarden, etc.)
4. Scan the QR code shown
5. Enter the 6-digit code from your app to confirm
6. 2FA is now active. Next time you log in, you'll need a code.

**⚠️ Important:** Save the backup codes (when implemented) in a safe place. If you lose your phone, you'll need them to recover access.

To **disable 2FA**: same page, but click **Disabilita 2FA** and enter a current code.

---

## 3. Forgot Your Password?

1. On the login page, click **Password dimenticata?**
2. Enter your email address
3. Click **Invia link di reset**
4. Check your email (also spam folder)
5. Click the link in the email (valid for 1 hour)
6. Enter a new password

If you don't receive the email within 5 minutes:
- Check that the email address is correct
- Verify with your administrator that your account is active

---

## 4. Using the Chat

The chat is the main way to interact with WorkMind.

### 4.1 Asking a Question

1. Type your question in the box at the bottom
2. Press Enter or click the **send** button
3. The AI responds, streaming the answer in real-time

### 4.2 What Can I Ask?

WorkMind is best at:
- ✅ Questions about documents in your knowledge base
- ✅ Summaries and explanations
- ✅ Drafting emails or text in a specific style
- ✅ Analysis of data you provide
- ✅ Italian and English (other languages supported but quality varies)

WorkMind is **not** suited for:
- ❌ Real-time information (current weather, stock prices)
- ❌ Tasks requiring browsing the web
- ❌ Highly precise mathematical calculations
- ❌ Legal or medical advice (always verify with a professional)

### 4.3 Tips for Better Answers

- **Be specific.** Instead of "Tell me about it", say "Summarize the protocol document I uploaded last week"
- **Provide context.** "Acting as our compliance officer, draft a response to..."
- **Ask follow-up questions** to refine answers
- **Request format.** "List the steps as a numbered list" or "Reply in a table"

### 4.4 Using Knowledge Base in Chat

When you ask a question, WorkMind automatically searches your company's knowledge base for relevant documents. The relevant excerpts are included in the AI's context.

If you want to disable this for a specific question (e.g., for a generic question), look for the toggle (planned feature).

### 4.5 Streaming Responses

Answers stream as they're generated, like ChatGPT. You'll see text appear word by word. If the connection is slow, you may see chunks of text instead of individual words.

If a response stops mid-stream:
- Check your internet connection
- Refresh the page
- Try the question again

---

## 5. Knowledge Base Search

For direct document search without the AI:

1. Click on **Knowledge Base** in the sidebar (or use the chat)
2. Enter your query
3. See ranked results with snippets
4. Click on a result to open the source document

### 5.1 What's in the Knowledge Base?

Your administrator uploads documents (PDF, Word, Excel, AutoCAD DXF, plain text) to the KB. These are processed:

1. Text is extracted
2. Split into chunks
3. Embedded as vectors (mathematical representations)
4. Stored in the database

When you search or chat, your query is matched against these chunks using semantic similarity (not keyword matching).

### 5.2 Adding Documents

If your role allows it, you can upload via:

1. **Knowledge Base** → **Upload**
2. Select file
3. Add title and description
4. Click **Upload**

Processing takes a few seconds for small files, longer for large PDFs.

---

## 6. Conversations Management

Past conversations are saved automatically.

### 6.1 Viewing History

Click **Conversazioni** in the sidebar to see all your past chats.

### 6.2 Searching Conversations

Use the search box to find conversations by title or content.

### 6.3 Continuing a Conversation

Click on a past conversation to open it. The full history is shown. You can continue with new messages — the AI has the full context.

### 6.4 Renaming a Conversation

By default, conversations are titled with the first user message. To rename:

1. Open the conversation
2. Click the title at the top
3. Edit and press Enter

### 6.5 Archiving / Deleting

- **Archive** removes from the main list but preserves data
- **Delete** is permanent and removes all messages

---

## 7. Updating Your Profile

Click on your name (bottom-left) → **Profilo**.

You can update:
- **Display name** — how others see you
- **Password** (current password required)
- **2FA settings** (see §2)

You **cannot** change:
- Email — contact your administrator
- Role — contact your administrator
- Organization — managed by admin

---

## 8. Mobile Use

WorkMind is responsive and works on mobile browsers (Safari, Chrome, Firefox).

For the best mobile experience:
- Add WorkMind to your home screen (acts like a PWA)
- Enable browser notifications (planned)
- Use Telegram/WhatsApp integration to chat outside the browser

### 8.1 Telegram Integration

If your organization has the Telegram connector enabled:

1. Search for your bot on Telegram (your admin has the bot username)
2. Send `/start` to associate your account
3. Chat with the bot — it's the same WorkMind AI
4. Send voice messages — they're transcribed and answered as text (or voice, if voice-output is enabled)

---

## 9. MEDIC Features

Available only to organizations in the **medic** sector.

### 9.1 Products

**Sidebar → Prodotti**

- View the catalog of products
- Search by name or code
- Add new products (admin only)
- Set low-stock thresholds

### 9.2 Inventory & Lots

For each product:
- See current stock quantity
- View individual lots with expiry dates
- Lots ordered FIFO (oldest first) for sales

### 9.3 Sales

**Sidebar → Vendite**

To record a sale:

1. Click **Nuova vendita**
2. Select product and quantity
3. Pick lot (or auto-FIFO)
4. Enter customer name (optional)
5. Click **Registra**

Stock is automatically deducted. The sale is recorded with timestamp, agent (you), and lot.

### 9.4 Agent Warehouse (Magazzino Agenti)

If you're an agent (sales rep with their own stock):

**Sidebar → Magazzino Agenti**

- See the products allocated to you
- Sell from your allocation (deducts from your assigned stock)
- Return unsold products to the main warehouse

Admins can view all agents' stock and allocate new product to agents.

### 9.5 Statistics

**Sidebar → Statistiche**

View:
- Sales by period (day, week, month)
- Top products
- Top agents
- Revenue
- Stock alerts (low/expiring)

### 9.6 Low Stock Alerts

If the **low stock alert** skill is enabled:
- Every 4 hours (configurable), the system checks for products below threshold
- Notifies via Telegram (or email)
- Listed in the Statistics page

---

## 10. Frequently Asked Questions

### 10.1 Why does the AI sometimes say "I don't know"?

WorkMind is designed to be honest about uncertainty. If your question is outside the knowledge base or AI's training, it'll say so rather than guess. Try rephrasing or providing more context.

### 10.2 Why is the response slow?

AI responses depend on:
- Provider (Claude is faster than DeepSeek; Ollama is fastest but less smart)
- Question length and KB context size
- Network latency

If responses are consistently slow, contact your administrator — they can adjust the AI provider settings.

### 10.3 Is my data private?

Yes. Your data:
- Stays on your organization's instance
- Is encrypted in transit (HTTPS)
- Is anonymized before being sent to external AI providers (PII like fiscal codes, phones, emails are masked)
- Is never used to train AI models

See the **Privacy Policy** for full details.

### 10.4 Can I use WorkMind for confidential information?

For most business confidential information: yes, especially if your admin uses Anthropic (Claude) which has strong privacy commitments.

For **highly sensitive** information (e.g., legal cases, medical records, government data), check with your admin about:
- Disabling external AI providers (use only local Ollama)
- Disabling KB indexing for specific documents
- Reviewing the data processing agreement

### 10.5 What if I see incorrect information?

AI can make mistakes (called "hallucinations"). Always verify critical information against the source document. If WorkMind cites a wrong source, please report to your admin.

### 10.6 Can I export my conversations?

Yes, contact your administrator to request an export. They can produce a JSON or PDF export of your data (right of access — GDPR Article 15).

### 10.7 Can I delete my account?

Yes. Contact your administrator to request deletion. Per GDPR, your data will be removed within 30 days (with some retention for legal/audit purposes).

### 10.8 Why was I logged out unexpectedly?

Your access token expires after 24 hours by default. The system tries to refresh automatically, but if your refresh token also expires (after 30 days of inactivity), you'll need to log in again.

### 10.9 Can I use multiple devices?

Yes. You can log in on phone, laptop, and desktop simultaneously. All conversations sync.

### 10.10 What languages does WorkMind support?

The interface is in **Italian** primarily. The AI responds in the language you write to it (well-tested: Italian, English; reasonable: French, Spanish, German).

---

## 11. Getting Help

If you encounter issues:

1. **Check this manual** for the relevant section
2. **Ask your organization's administrator** — they have access to logs and can diagnose
3. **Report a bug** with as much detail as possible:
   - What you were doing
   - What you expected
   - What happened instead
   - Screenshots if relevant
   - Date and time

---

## 12. Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Enter` | Send message |
| `Shift + Enter` | New line in message |
| `Ctrl + /` (or `Cmd + /`) | Focus message input |
| `Esc` | Close modal/panel |

(More shortcuts planned.)

---

**Thanks for using WorkMind. Build, ask, learn.**
