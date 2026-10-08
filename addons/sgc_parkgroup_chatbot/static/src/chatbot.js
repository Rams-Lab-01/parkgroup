// Lazy-loads the pinned n8n chat widget after the page is idle, skipping the website editor.
const N8N_CHAT = 'https://cdn.jsdelivr.net/npm/@n8n/chat@1.41.3/dist';
const WEBHOOK = 'https://n8n.sgctech.ai/webhook/8d5d3e37-32e1-4e76-b92a-63c607e97555/chat';

async function boot() {
    if (document.body.classList.contains('editor_enable') || window.self !== window.top) {
        return;
    }
    const css = document.createElement('link');
    css.rel = 'stylesheet';
    css.href = `${N8N_CHAT}/style.css`;
    // Brand overrides must come after the vendor sheet.
    document.head.insertBefore(css, document.head.querySelector('link[href*="sgc_parkgroup_chatbot"]'));
    const { createChat } = await import(`${N8N_CHAT}/chat.bundle.es.js`);
    createChat({
        webhookUrl: WEBHOOK,
        mode: 'window',
        showWelcomeScreen: false,
        defaultLanguage: 'en',
        initialMessages: [
            'Welcome to PARK Group! 👋',
            'Ask me about our projects, or say "menu" to see what I can help with.',
        ],
        i18n: {
            en: {
                title: 'PARK Group Assistant',
                subtitle: '“Building with Purpose”',
                footer: '',
                getStarted: 'New conversation',
                inputPlaceholder: 'Type your message…',
                closeButtonTooltip: 'Close chat',
            },
        },
    });
}

if ('requestIdleCallback' in window) {
    requestIdleCallback(boot, { timeout: 3000 });
} else {
    setTimeout(boot, 1500);
}
