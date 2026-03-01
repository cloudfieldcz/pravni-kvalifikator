// SSE client + UI logic for the qualification pipeline

document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('qualify-form');
    const submitBtn = document.getElementById('submit-btn');
    const progressSection = document.getElementById('progress-section');
    const progressContainer = document.getElementById('progress-container');

    if (!form) return;

    // Agent display names
    const AGENT_NAMES = {
        'law_identifier': 'Identifikace zákonů',
        'head_classifier': 'Klasifikace hlav',
        'paragraph_selector': 'Selekce paragrafů',
        'qualifier': 'Kvalifikace',
        'reviewer': 'Review',
    };

    const STATUS_ICONS = {
        'started': '▶',
        'working': '▶',
        'completed': '✓',
        'error': '✗',
    };

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        submitBtn.disabled = true;
        submitBtn.textContent = 'Zpracovávám...';

        const popisSkutku = document.getElementById('popis-skutku').value;
        const typ = form.querySelector('input[name="typ"]:checked').value;

        // Reset UI
        progressSection.classList.remove('hidden');
        progressContainer.innerHTML = '';

        try {
            // POST /qualify
            const response = await fetch('/qualify', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ popis_skutku: popisSkutku, typ: typ }),
            });

            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || 'Chyba při odesílání');
            }

            const data = await response.json();
            const qualificationId = data.qualification_id;

            // Connect SSE
            connectSSE(qualificationId);
        } catch (err) {
            progressContainer.innerHTML = `<p class="error">Chyba: ${err.message}</p>`;
            submitBtn.disabled = false;
            submitBtn.textContent = 'Kvalifikovat';
        }
    });

    function connectSSE(qualificationId) {
        const evtSource = new EventSource(`/qualify/${qualificationId}/stream`);

        evtSource.addEventListener('agent_update', (e) => {
            const event = JSON.parse(e.data);
            updateProgress(event);
        });

        evtSource.addEventListener('done', () => {
            evtSource.close();
            // Redirect to full result page (rendered server-side via result.html)
            window.location.href = `/qualify/${qualificationId}`;
        });

        evtSource.addEventListener('error', () => {
            evtSource.close();
            // Redirect to result page — it handles errors too
            window.location.href = `/qualify/${qualificationId}`;
        });
    }

    function updateProgress(event) {
        const agentId = event.agent_name;
        let agentEl = document.getElementById(`agent-${agentId}`);

        if (!agentEl) {
            agentEl = document.createElement('div');
            agentEl.id = `agent-${agentId}`;
            agentEl.className = 'agent-progress';
            progressContainer.appendChild(agentEl);
        }

        const icon = STATUS_ICONS[event.stav] || '○';
        const name = AGENT_NAMES[agentId] || agentId;
        const statusClass = `status-${event.stav}`;

        agentEl.className = `agent-progress ${statusClass}`;
        agentEl.innerHTML = `
            <span class="agent-icon">${icon}</span>
            <span class="agent-name">${name}</span>
            <span class="agent-message">${event.zprava}</span>
        `;
    }
});
