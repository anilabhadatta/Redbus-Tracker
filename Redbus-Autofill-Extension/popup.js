document.addEventListener('DOMContentLoaded', () => {
    // Load saved data
    chrome.storage.local.get(['redbusAutofillData'], (result) => {
        if (result.redbusAutofillData) {
            const data = result.redbusAutofillData;
            for (let i = 0; i < 3; i++) {
                if (data.passengers[i]) {
                    document.getElementById(`p${i+1}-name`).value = data.passengers[i].name || '';
                    document.getElementById(`p${i+1}-id`).value = data.passengers[i].id || '';
                }
            }
            if (data.cancellation === 'yes') {
                document.getElementById('cancelYes').checked = true;
            } else {
                document.getElementById('cancelNo').checked = true;
            }
        }
    });

    const saveData = () => {
        const passengers = [];
        for (let i = 1; i <= 3; i++) {
            const name = document.getElementById(`p${i}-name`).value.trim();
            const id = document.getElementById(`p${i}-id`).value.trim();
            if (name || id) {
                passengers.push({ name, id });
            }
        }
        const cancellation = document.querySelector('input[name="cancellation"]:checked').value;
        const data = { passengers, cancellation };
        chrome.storage.local.set({ redbusAutofillData: data });
        return data;
    };

    // Auto-save on input change
    document.querySelectorAll('input').forEach(input => {
        input.addEventListener('input', saveData);
        input.addEventListener('change', saveData);
    });

    document.getElementById('autofillBtn').addEventListener('click', async () => {
        const data = saveData();

        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        if (!tab || !tab.url || !tab.url.includes("redbus.in")) {
            const btn = document.getElementById('autofillBtn');
            btn.textContent = 'Saved! (Open Redbus first)';
            setTimeout(() => { btn.textContent = 'Save Details & Autofill Now'; }, 2000);
            return;
        }

        const btn = document.getElementById('autofillBtn');
        btn.textContent = 'Injecting...';
        btn.style.opacity = '0.7';

        try {
            // Always inject the content script fresh — this resolves the
            // "Receiving end does not exist" error when the tab was open before the extension loaded.
            await chrome.scripting.executeScript({
                target: { tabId: tab.id },
                files: ['content.js']
            });

            // Small delay to let the script initialise
            await new Promise(r => setTimeout(r, 300));

            // Now send the message — the content script is guaranteed to be listening
            chrome.tabs.sendMessage(tab.id, { action: "doAutofill", data: data }, () => {
                if (chrome.runtime.lastError) {
                    console.warn("sendMessage error (non-fatal):", chrome.runtime.lastError.message);
                }
            });

            btn.textContent = 'Autofilling...';
            setTimeout(() => {
                btn.textContent = 'Save Details & Autofill Now';
                btn.style.opacity = '1';
            }, 3000);
        } catch (err) {
            console.error("Injection error:", err);
            btn.textContent = 'Error — see console';
            btn.style.opacity = '1';
            setTimeout(() => { btn.textContent = 'Save Details & Autofill Now'; }, 3000);
        }
    });
});
