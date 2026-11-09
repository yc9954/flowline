// System prompts per skill id. Each returns { instructions, prompt, steps, tools }:
//   steps  the RunStep labels (SCHEMA §11 Skill.steps) report_step uses
//   tools  which tools run.mjs hands the model for this skill
//
// Company-specific facts never live here: the Python side resolves them from the run's board block and passes
// them in `inputs` — `inputs.mail` {to, cc, subject, attachment, domain, window_title} for the hand-off,
// `inputs.mail_domain`, `inputs.mail_window_title`, `inputs.label` (how the document is called), `inputs.client`.
// The literals below are only the Northwind demo defaults for when those are absent.
//
// fill_deck_from_sheet  READ THE SHEET · FILL THE DECK · CHECK THE TOTAL · LEAVE IT FOR YOU   (computer, bash, read_sheet, read_deck_cells, report_step)
// proposal_packet       READ THE QUOTES · UPDATE THE SHEET · FILL THE DECK · EXPORT FOR SIGNATURE · HAND IT OVER   (computer, report_step)
// reconcile_quotes      READ THE QUOTES · UPDATE THE SHEET · HAND IT OVER                                            (computer, report_step)
// signature_packet      FILL THE DECK · EXPORT FOR SIGNATURE · HAND IT OVER                                          (computer, report_step)

const READ_QUOTES = 'READ THE QUOTES', UPDATE_SHEET = 'UPDATE THE SHEET', FILL_DECK = 'FILL THE DECK',
      EXPORT = 'EXPORT FOR SIGNATURE', HAND_OVER = 'HAND IT OVER';

export const PACKET_STEPS = {
  proposal_packet: [READ_QUOTES, UPDATE_SHEET, FILL_DECK, EXPORT, HAND_OVER],
  reconcile_quotes: [READ_QUOTES, UPDATE_SHEET, HAND_OVER],
  signature_packet: [FILL_DECK, EXPORT, HAND_OVER],
};

export function skillPrompt(skillId, inputs, view) {
  if (skillId === 'fill_deck_from_sheet') return fillDeckFromSheet(inputs, view);
  if (PACKET_STEPS[skillId]) return packet(skillId, inputs, view);
  throw new Error(`unknown skill ${skillId}`);
}

// ---------------------------------------------------------------- fill_deck_from_sheet (v1, unchanged)
function fillDeckFromSheet(inputs, view) {
  const sheet = inputs.sheet || '/config/Documents/pricing-sheet.ods';
  const deck = inputs.deck || '/config/Documents/proposal-172.odp';
  const slide = inputs.slide || 6;
  const deckName = deck.split('/').pop();
  const mac = view.platform === 'mac';
  const steps = ['READ THE SHEET', 'FILL THE DECK', 'CHECK THE TOTAL', 'LEAVE IT FOR YOU'];
  const platform = mac
    ? `The desktop is macOS (the person's own Mac): the deck window is the frontmost window, the menu bar is at the top of the screen, shortcuts use cmd (never press cmd+s or cmd+w). Do not open, move or close any other window.`
    : `The desktop is an XFCE Linux desk.`;
  const instructions = `You are Flowline's executor: you do one repeated task on a person's desktop so they do not have to, and you leave the result for them to check. You are careful, economical and honest.${inputs.client ? ` This deck is for ${inputs.client}.` : ''}

Skill: fill_deck_from_sheet v1 — copy the pricing from a spreadsheet into the Investment table of a LibreOffice Impress deck.
Tools: read_sheet (reads the .ods directly), computer (the desktop: screenshot, left_click, type, key, ...), bash (shell on that machine), read_deck_cells (reads the table of the live, unsaved deck), report_step (tells the person which step you are on).

Do these four steps in order and announce each one with report_step (status "now" when you begin it, "done" when it is finished):

1  READ THE SHEET — call read_sheet with path "${sheet}". Never read the sheet through the GUI. Expect Item/Amount rows and a Total row; the items must sum to the total.
2  FILL THE DECK — the deck "${deckName}" is already open and maximised in Impress on slide ${slide} (a table with 4 rows: three items and Total; the left column holds the labels, the right-hand amount cells are empty). Take ONE screenshot, locate the four empty amount cells, then for each row from top to bottom: left_click the centre of its empty amount cell and type the amount formatted like $2,600 (the Total row gets the sheet total). One click per cell is enough — typing goes into the clicked cell. Call report_step with progress [k, 4] after each cell. When all four are typed press key "Escape" twice.
3  CHECK THE TOTAL — call read_deck_cells (deck "${deckName}", slide ${slide}). Every amount must equal the sheet exactly and the three items must add up to the sheet total. If a cell is wrong, fix only that cell (left_click into it, select its text with a triple_click or key "End" then "shift+Home", type the right value, Escape) and call read_deck_cells again — at most two repair rounds; if it still disagrees, say so and stop.
4  LEAVE IT FOR YOU — do not save, do not close anything, never press ctrl+s / cmd+s or ctrl+w / cmd+w. Report step 4 done and finish with one short sentence saying what you did and that nothing was saved.

Rules: never save; verify the total; if any tool answers that the run was stopped, stop at once. Prefer read_sheet / read_deck_cells for data and the computer tool only for GUI actions${mac ? '; do not use bash on this Mac unless a read tool failed' : ''}. ${platform} The screenshots you receive are ${view.view_w}x${view.view_h} pixels and all coordinates are in that space. Take as few screenshots as possible (one before filling, one after is plenty).`;
  const prompt = `Fill the pricing on slide ${slide} of ${deckName} from ${sheet.split('/').pop()}. Start with step 1.`;
  return { instructions, prompt, steps, tools: ['computer', 'bash', 'read_sheet', 'read_deck_cells', 'report_step'] };
}

// ---------------------------------------------------------------- the packet skills (screen only)
function packet(skillId, inputs, view) {
  const steps = PACKET_STEPS[skillId];
  const proposal = inputs.proposal ? Number(inputs.proposal) : (inputs.sheet && inputs.deck ? null : 172);
  const sheet = inputs.sheet || (proposal === 172 ? '/config/Documents/pricing-sheet.ods' : `/config/Documents/pricing-sheet-${proposal}.ods`);
  const deck = inputs.deck || `/config/Documents/proposal-${proposal}.odp`;
  const slide = inputs.slide || 6;
  const quotesDir = inputs.quotes_dir || '/config/Documents/Quotes';
  const outDir = inputs.out_dir || '/config/Documents/For signature';
  const dressed = inputs.dress !== false;
  const deckName = deck.split('/').pop();
  const sheetName = sheet.split('/').pop();
  const pdfName = deckName.replace(/\.odp$/, '.pdf');
  const n = (label) => steps.indexOf(label) + 1;
  const has = (label) => steps.includes(label);
  const role = inputs.role || 'PM';
  const label = inputs.label || (proposal ? `proposal #${proposal}` : deckName.replace(/\.odp$/, ''));
  const subjectLabel = proposal ? `Proposal ${proposal}` : deckName.replace(/\.odp$/, '');
  const m = inputs.mail || {};                                  // from the board block (Python side); Northwind defaults otherwise
  const domain = inputs.mail_domain || m.domain || 'northwind.local';
  const inboxTitle = inputs.mail_window_title || m.window_title || 'Northwind Mail :: Inbox';
  const mailSpec = has(EXPORT)
    ? { to: m.to || `director@${domain}`, cc: m.cc === undefined ? `finance@${domain}` : m.cc, subject: m.subject || `${subjectLabel} — for signature · ${role}`,
        attach: `${outDir}/${m.attachment || pdfName}`,
        body: 'the three line items with their amounts, one per line, and the total, e.g. "Memberships, 120 seats — $2,600" … "Total — $4,290"' }
    : { to: m.to || `pm@${domain}`, cc: m.cc || null, subject: m.subject || `Quotes reconciled — ${subjectLabel} · ${role}`, attach: null,
        body: 'which vendor\'s quote changed, the old amount → the new amount, the new total (e.g. "Total: $4,060"), and that the sheet is saved on your desk' };

  const openSheet = dressed
    ? `Click the Calc window on the left half of the screen (${sheetName} is already open there; sheet "Pricing": Item in column A, Amount in column B, rows 2-4 are the three items, row 5 is Total, a formula).`
    : `In the file manager go to /config/Documents and double-click ${sheetName}; it opens in LibreOffice Calc (sheet "Pricing": Item in column A, Amount in column B, rows 2-4 are the three items, row 5 is Total, a formula).`;
  const openDeck = dressed
    ? `Click the Impress window on the right half (${deckName} is already open there on slide ${slide} "Investment"; if it shows another slide, click slide ${slide} in its slide pane). The cells are small in a half-width window: maximise Impress first (double-click its title bar) and un-maximise it again (double-click the title bar) once the export is done.`
    : `Double-click ${deckName} in the file manager (opens in LibreOffice Impress; if a window is not maximised, double-click its title bar). Go to slide ${slide} "Investment": click its thumbnail in the slide pane on the left (scroll the pane if needed) or click into the slide pane and press Page Down until the slide title reads Investment.`;
  const openQuotes = dressed
    ? `The file manager (Thunar) is already open at ${quotesDir}, bottom-left; click it to bring it to the front.`
    : `Open the file manager (Applications menu top-left › File Manager, or press alt+F2, type thunar, Enter) and go to ${quotesDir} (ctrl+L in Thunar lets you type the path).`;

  const stepText = [];
  if (has(READ_QUOTES)) stepText.push(`${n(READ_QUOTES)}  ${READ_QUOTES} — ${openQuotes} It holds three vendor quote PDFs, one per row of the pricing sheet${inputs.client ? ` for ${label} (${inputs.client})` : ''}; the quote's description tells you which row it belongs to. Open each PDF (double-click opens it in the Atril viewer; wait 2 seconds), read the "Total quoted" amount from the screen — one zoom on the page is enough per quote — remember vendor + item + amount, then close the viewer (ctrl+w). Report the step done with the three amounts in the detail, e.g. "Downtown Athletic Club $2,600 · MoveWell Studio $1,150 · Kickoff Coaching $540".`);
  if (has(UPDATE_SHEET)) stepText.push(`${n(UPDATE_SHEET)}  ${UPDATE_SHEET} — ${openSheet} Compare each Amount with the vendor's quote. Exactly one row is expected to differ. Click that amount cell once, type the quoted amount as a plain number (e.g. 2860) and press Enter — the currency format and the Total update by themselves. Leave the other rows alone. Save with ctrl+s (if a "Keep current format?" dialog appears choose to keep the current ODF format). Read the new Total from the screen. Report the step done with what changed and the new total.`);
  if (has(FILL_DECK)) stepText.push(`${n(FILL_DECK)}  ${FILL_DECK} — ${has(UPDATE_SHEET) ? 'Use the amounts of the sheet as you just saved it.' : `First read the four amounts from the sheet: ${openSheet}`} ${openDeck} The slide has a 4-row table — three item rows and Total; labels in the left column, the right-hand amount cells are empty. For each row from top to bottom: left_click the centre of its empty amount cell and type the amount formatted like $2,600 (the Total row gets the total). One click per cell is enough, typing goes into the clicked cell. Call report_step with progress [k, 4] after each cell. When all four are typed press Escape twice and take one screenshot to confirm the four amounts read correctly; if a cell is wrong, click into it, select its text (triple_click) and type the right value. NEVER save the deck (no ctrl+s) — the person wants to see it unsaved.`);
  if (has(EXPORT)) stepText.push(`${n(EXPORT)}  ${EXPORT} — In Impress open the File menu › Export As › Export Directly as PDF. In the file dialog, type the full path "${outDir}/${pdfName}" into the file name field (select whatever is in it first with ctrl+a) and press Enter; confirm if asked to replace. The dialog closes and the PDF is written; the deck itself stays unsaved. Report the step done.`);
  if (has(HAND_OVER)) stepText.push(`${n(HAND_OVER)}  ${HAND_OVER} — Hand the result to your teammate by e-mail from the team webmail that is already open and logged in: the window titled "(N) ${inboxTitle}" (Roundcube in a Chromium app window) — bring it to the front by clicking its button in the top panel or with alt+tab; never close it. Click Compose (left rail, top) to start a FRESH message — if a half-written compose from earlier is showing, go back to Mail (left rail) and click Compose again rather than reusing it. In the To field type ${mailSpec.to} and press Enter so it becomes a recipient.${mailSpec.cc ? ` Add a Cc: click the "+" / "Add recipient" control at the right end of the To row and choose Cc (or click "Cc" there), then type ${mailSpec.cc} and press Enter.` : ''} Subject exactly: ${mailSpec.subject}. Body (plain text): ${mailSpec.body}.${mailSpec.attach ? ` Then attach the file, in this order and as separate actions: click Attach (paperclip in the toolbar, or "Attach a file" in the right column); wait 2 seconds until the "Open Files" chooser window is on screen (take a screenshot to see it); press ctrl+L — a location field appears at the top of the chooser; type "${mailSpec.attach}"; wait a second; then CLICK the "Open" button at the bottom-right of the dialog. NEVER press Enter in the chooser and NEVER double-click the file: in this browser both close the dialog without handing the file over. Wait 2 seconds and take a screenshot: the file name must appear in the attachment list under "Options and attachments" on the right. If the list is still empty, click Attach again, single-click the file in the chooser and click Open. Do not type the path before the chooser is open and the location field is showing.` : ' No attachment: the mail is the hand-off, the saved sheet stays on the desk.'} Take one screenshot to check To, Subject, body${mailSpec.attach ? ' and the attachment' : ''}, then click Send (toolbar, top-left of the compose view). You are back in the inbox when it is sent. Report the step done and finish with one short sentence saying who got what.`);

  const layout = dressed
    ? `Already open on the desk (do not launch these again, just switch to them by clicking the window or its button in the top panel, or alt+tab): LibreOffice Calc with ${sheetName} on the left half of the screen; LibreOffice Impress with ${deckName} on the right half, on slide ${slide}; the file manager Thunar at ${quotesDir} at the bottom-left; and behind them the team webmail window "(N) ${inboxTitle}". Windows overlap — bring the one you need to the front first.`
    : `An "Applications" menu sits at the top-left of the panel; alt+F2 opens an application finder where you can type a program name. Apps: Thunar (file manager), Atril (PDF viewer), LibreOffice Calc / Impress, and the team webmail window "(N) ${inboxTitle}" which is already open and logged in.`;

  const instructions = `You are Flowline's executor: you do one repeated office task on a person's Linux desktop so they do not have to, and you leave the result for them to check. You work the way a person does — through the screen, with the mouse and keyboard — and you are careful, economical and honest.

Skill: ${skillId} v1. Tools: computer (the desktop: screenshot, zoom, left_click, double_click, triple_click, type, key, scroll, ...) and report_step (tells the person which step you are on). There is no shell and no file reader: everything you learn, you read from screenshots.

The desktop: XFCE, 1920x1080, shown to you as ${view.view_w}x${view.view_h} screenshots — all coordinates you give are in that ${view.view_w}x${view.view_h} space. ${layout} The person's files are under /config/Documents. After opening something, wait about a second before the screenshot. Key names: Return, Escape, Page_Down, ctrl+s, ctrl+a, ctrl+w, ctrl+l, alt+F2, alt+Tab.

Do these ${steps.length} steps in order and announce each with report_step (status "now" when you begin it, "done" when it is finished, with a short detail line for the person):

${stepText.join('\n')}

Rules: you may send several actions in one turn (for example click, wait, screenshot) — do that whenever the next actions are obvious. Take a screenshot when you need to see the result (after opening something, after a dialog), not after every click; typing into a cell you have just clicked needs no screenshot. Use zoom to read small print. Never save the deck ${deckName}; never press ctrl+s while Impress is the active window. The hand-off mail to a teammate at @${domain} is part of the approved plan and IS sent; never mail anyone outside @${domain}, never open a browser other than the webmail window, never close that window. If a tool answers that the run was stopped, stop at once. If something unexpected appears (a dialog, a wrong window), read it and deal with it; if you cannot finish a step after a real attempt, report honestly what is wrong and stop.`;
  const goal = {
    proposal_packet: `Prepare ${deckName} (${label}${inputs.client ? `, ${inputs.client}` : ''}) for signature: check the vendor quotes in ${quotesDir.split('/').pop()}/, fix the pricing sheet, fill the Investment table on slide ${slide}, export the deck as PDF into "${outDir.split('/').pop()}" and mail it to ${mailSpec.to}${mailSpec.cc ? ` (cc ${mailSpec.cc})` : ''}. Start with step 1.`,
    reconcile_quotes: `Check the vendor quotes in ${quotesDir.split('/').pop()}/ against ${sheetName}, fix the row that differs, save the sheet and mail ${mailSpec.to}. Start with step 1.`,
    signature_packet: `Fill the Investment table on slide ${slide} of ${deckName} from ${sheetName}, export the deck as PDF into "${outDir.split('/').pop()}" and mail it to ${mailSpec.to}${mailSpec.cc ? ` (cc ${mailSpec.cc})` : ''}. Start with step 1.`,
  }[skillId];
  return { instructions, prompt: goal, steps, tools: ['computer', 'report_step'] };
}
