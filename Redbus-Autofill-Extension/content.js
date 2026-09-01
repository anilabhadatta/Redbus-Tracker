// Guard against being injected multiple times into the same page
if (!window.__redbusAutofillLoaded) {
    window.__redbusAutofillLoaded = true;

    const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

    function triggerReactInput(element, value) {
        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
        if (nativeInputValueSetter) {
            nativeInputValueSetter.call(element, value);
            element.dispatchEvent(new Event('input', { bubbles: true }));
            element.dispatchEvent(new Event('change', { bubbles: true }));
        } else {
            element.value = value;
            element.dispatchEvent(new Event('input', { bubbles: true }));
        }
    }

    function findVisibleElementContains(text) {
        const els = [...document.querySelectorAll('*')].filter(el =>
            el.children.length === 0 &&
            el.textContent.toLowerCase().includes(text.toLowerCase())
        );
        return els.find(el => el.getBoundingClientRect().width > 0 && el.getBoundingClientRect().height > 0);
    }

    /** Returns the current set of visible "ID number" inputs as a Set (for diffing) */
    function getVisibleIdNumberInputs() {
        return new Set(
            Array.from(document.querySelectorAll('input')).filter(el => {
                const ph = (el.placeholder || '').toLowerCase();
                const rect = el.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0 &&
                    (ph.includes('id number') || ph.includes('aadhaar') || ph.includes('enter id') || ph.includes('number'));
            })
        );
    }

    async function autofillRedbus(data) {
        console.log("[Redbus Autofill] Starting with data:", data);

        for (const p of data.passengers) {
            if (!p.name || !p.id) continue;

            console.log(`[Redbus Autofill] Processing passenger: ${p.name}`);

            // ── 1. Snapshot existing ID-number inputs BEFORE we touch anything ──
            const idInputsBefore = getVisibleIdNumberInputs();

            // ── 2. Find the passenger name leaf node ──
            const allLeaves = Array.from(document.querySelectorAll('*')).filter(el => el.children.length === 0);
            const nameDiv = allLeaves.find(el => el.textContent.trim() === p.name.trim());

            if (!nameDiv) {
                console.log(`[Redbus Autofill] Passenger "${p.name}" not found on page. Skipping.`);
                continue;
            }

            // ── 3. Find the row container (swipeContainer / listItem) ──
            let row = nameDiv.parentElement;
            for (let i = 0; i < 6; i++) {
                if (!row || row === document.body) break;
                const cls = row.className || '';
                if (cls.includes('swipeContainer') || cls.includes('listItem') || cls.includes('swipeable')) break;
                row = row.parentElement;
            }

            // ── 4. Click the checkbox / right-container ──
            let clickTarget = row ? row.querySelector('[class*="rightListCont"], [class*="customCheckbox"], input[type="checkbox"]') : null;
            if (clickTarget) {
                clickTarget.click();
                console.log("[Redbus Autofill] Clicked passenger checkbox/row");
            } else {
                nameDiv.click();
                console.log("[Redbus Autofill] Fallback: clicked passenger name");
            }

            await delay(1200);

            // ── 5. Click the "ID type" dropdown ──
            // Snapshot id-type inputs: visible inputs whose placeholder says "id type" or readonly
            const allVisible = Array.from(document.querySelectorAll('input')).filter(
                el => el.getBoundingClientRect().width > 0
            );

            // "ID type" dropdowns — typically readonly, placeholder "ID Type"
            const idTypeInputs = allVisible.filter(el => {
                const ph = (el.placeholder || '').toLowerCase();
                return ph.includes('id type') || ph.includes('select id');
            });

            const idTypeInput = idTypeInputs[idTypeInputs.length - 1]; // last = most recently added

            if (idTypeInput) {
                idTypeInput.click();
                console.log("[Redbus Autofill] Clicked ID type dropdown");
            } else {
                // fallback: try wrapper divs
                const wrapper = Array.from(document.querySelectorAll('[class*="dropdownWrap"]'))
                    .find(el => el.getBoundingClientRect().width > 0);
                if (wrapper) {
                    wrapper.click();
                    console.log("[Redbus Autofill] Clicked dropdown wrapper fallback");
                } else {
                    console.warn("[Redbus Autofill] ID Type dropdown not found.");
                }
            }

            await delay(1200);

            // ── 6. Select "Aadhaar Card" from the bottom-sheet ──
            const aadhaarEl = Array.from(document.querySelectorAll('*')).find(el =>
                el.children.length === 0 &&
                el.textContent.trim() === 'Aadhaar Card' &&
                el.getBoundingClientRect().width > 0
            );

            if (aadhaarEl) {
                aadhaarEl.click();
                console.log("[Redbus Autofill] Selected 'Aadhaar Card'");
            } else {
                console.warn("[Redbus Autofill] 'Aadhaar Card' option not found.");
            }

            await delay(800);

            // ── 7. Confirm / close the bottom sheet ──
            const confirmBtn = Array.from(document.querySelectorAll('button')).find(el =>
                (el.textContent.trim() === 'Confirm' || el.textContent.trim() === 'Done' || el.textContent.trim() === 'Continue') &&
                el.getBoundingClientRect().width > 0
            );
            if (confirmBtn) {
                confirmBtn.click();
                console.log("[Redbus Autofill] Clicked Confirm on modal");
            } else {
                const closeBtn = document.querySelector('[class*="closeIcon"], [class*="close-icon"], [aria-label="Close"]');
                if (closeBtn) { closeBtn.click(); console.log("[Redbus Autofill] Closed modal via X"); }
            }

            await delay(1200);

            // ── 8. Find THIS passenger's ID-number input by diffing ──
            // The input that appeared after we clicked is guaranteed to be for this passenger.
            const idInputsAfter = getVisibleIdNumberInputs();
            const newInputs = [...idInputsAfter].filter(el => !idInputsBefore.has(el));

            let idInput = null;

            if (newInputs.length > 0) {
                // Prefer the first newly-appeared input
                idInput = newInputs[0];
                console.log("[Redbus Autofill] Found new ID input via DOM diff");
            } else {
                // Fallback: find the empty "ID number" input closest to the passenger's name in the DOM
                const allIdInputs = [...idInputsAfter];
                // Try to find the empty one that is inside / after the passenger's row
                const emptyIdInputs = allIdInputs.filter(el => !el.value);
                if (emptyIdInputs.length > 0) {
                    // Pick the one closest to the nameDiv in DOM order
                    idInput = emptyIdInputs.reduce((closest, el) => {
                        const pos = el.compareDocumentPosition(nameDiv);
                        const closestPos = closest.compareDocumentPosition(nameDiv);
                        // Prefer elements that come AFTER the nameDiv (bit 2 = FOLLOWING)
                        return (pos & Node.DOCUMENT_POSITION_FOLLOWING) ? el : closest;
                    });
                    console.log("[Redbus Autofill] Using closest empty ID input fallback");
                }
            }

            if (idInput) {
                idInput.focus();
                triggerReactInput(idInput, p.id);
                console.log("[Redbus Autofill] Filled Aadhaar ID:", p.id);
            } else {
                console.warn("[Redbus Autofill] Could not find Aadhaar ID input for:", p.name);
            }

            await delay(800);
        }

        // ── Free Cancellation ──
        if (data.cancellation) {
            console.log(`[Redbus Autofill] Free Cancellation: ${data.cancellation}`);
            if (data.cancellation === 'yes') {
                const btn = document.querySelector('#fcConfirmText') || findVisibleElementContains('Add Free Cancellation');
                if (btn) btn.click();
                else console.warn("[Redbus Autofill] 'Add Free Cancellation' not found.");
            } else {
                const btn = document.querySelector('#fcRejectText') || findVisibleElementContains("Don't add Free Cancellation");
                if (btn) btn.click();
                else console.warn("[Redbus Autofill] 'Don't add Free Cancellation' not found.");
            }
            await delay(800);
        }

        // ── Continue Booking ──
        const continueBtn =
            Array.from(document.querySelectorAll('button')).find(el =>
                (el.textContent.toLowerCase().includes('continue booking') ||
                 el.textContent.toLowerCase().includes('proceed to pay')) &&
                el.getBoundingClientRect().width > 0
            ) || findVisibleElementContains('continue booking') || findVisibleElementContains('proceed to pay');

        if (continueBtn) {
            continueBtn.click();
            console.log("[Redbus Autofill] Clicked 'Continue Booking'");
        } else {
            console.warn("[Redbus Autofill] 'Continue Booking' button not found.");
        }

        console.log("[Redbus Autofill] Done!");
    }

    // ── Auto-run when the passenger section becomes visible ──
    let autoHasRun = false;

    function checkAndAutoRun() {
        if (autoHasRun) return;
        const wrapper =
            document.getElementById('coTravellerWrapper') ||
            document.getElementById('custInfoContainer') ||
            document.querySelector('[class*="coTravellerWrapper"]');
        if (!wrapper || wrapper.getBoundingClientRect().height === 0) return;

        autoHasRun = true;
        console.log("[Redbus Autofill] Passenger section detected. Auto-running in 1.5 s...");

        chrome.storage.local.get(['redbusAutofillData'], (result) => {
            if (result.redbusAutofillData?.passengers?.length > 0) {
                setTimeout(() => autofillRedbus(result.redbusAutofillData), 1500);
            } else {
                console.log("[Redbus Autofill] No saved data found.");
            }
        });
    }

    const observer = new MutationObserver(checkAndAutoRun);
    observer.observe(document.body, { childList: true, subtree: true });
    setTimeout(checkAndAutoRun, 1000);

    // ── Manual trigger from popup ──
    chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
        if (request.action === 'doAutofill') {
            autoHasRun = true;
            autofillRedbus(request.data);
            sendResponse({ status: 'started' });
        }
        return true;
    });

    console.log("[Redbus Autofill] Content script loaded.");
}
