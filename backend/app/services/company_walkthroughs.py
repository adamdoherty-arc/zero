"""Curated step-by-step walkthroughs for ADA AI LLC setup tasks.

Each walkthrough is a structured guide that tells Adam exactly which website to
visit, what fields to fill in, what to save as evidence, and what unlocks next.
The Company Dashboard Review service attaches the matching walkthrough to each
task review packet so it appears in the task detail drawer.
"""

from __future__ import annotations

import re
from typing import Any, Optional


def _step(
    title: str,
    instruction: str,
    *,
    url: Optional[str] = None,
    button: Optional[str] = None,
    fields: Optional[list[dict[str, str]]] = None,
    gotcha: Optional[str] = None,
    completion: Optional[str] = None,
) -> dict[str, Any]:
    step: dict[str, Any] = {"title": title, "instruction": instruction}
    if url:
        step["url"] = url
    if button:
        step["button"] = button
    if fields:
        step["fields"] = fields
    if gotcha:
        step["gotcha"] = gotcha
    if completion:
        step["completion_check"] = completion
    return step


EIN_WALKTHROUGH: dict[str, Any] = {
    "title": "Apply for ADA AI LLC's EIN with the IRS",
    "time_required": "20 minutes (must finish in one sitting; the IRS app times out after 15 min idle)",
    "cost": "Free. Never pay a 'filing service' for an EIN.",
    "best_time": "Weekdays 7am - 10pm Eastern (the IRS app is offline outside those hours)",
    "prerequisites": [
        "Florida LLC is approved on Sunbiz (you should have the document number from your Articles of Organization).",
        "You decided who the Responsible Party is (almost always you, Adam Doherty, with your SSN).",
        "You have your full legal name, SSN, and the LLC's principal business address.",
        "You have a quiet 20 minute block - the IRS application cannot be saved and resumed.",
    ],
    "steps": [
        _step(
            "Go to the official IRS EIN application",
            "Open this exact URL in your browser. Do NOT use 'irs-ein-tax-id.com' or 'irs.com' or any paid filing service - they charge $200-$300 for a service the IRS gives you for free.",
            url="https://sa.www4.irs.gov/applyein/individual/index.jsp",
            completion="You see a page that says 'Apply for an Employer Identification Number (EIN) Online' on irs.gov.",
        ),
        _step(
            "Click Begin Application",
            "Read the intro page once, then click the blue 'Begin Application' button at the bottom.",
            button="Begin Application",
        ),
        _step(
            "Choose entity type: Limited Liability Company (LLC)",
            "On the 'What type of legal structure is applying for an EIN?' page, select Limited Liability Company.",
            fields=[{"label": "Legal Structure", "value": "Limited Liability Company (LLC)"}],
            completion="Click Continue. You see a screen explaining LLC tax classification.",
        ),
        _step(
            "Confirm LLC details",
            "Tell the IRS this is a single-member LLC registered in Florida.",
            fields=[
                {"label": "Number of LLC Members", "value": "1"},
                {"label": "State where LLC is located", "value": "Florida"},
            ],
            gotcha="A single-member LLC is treated as a disregarded entity for federal taxes by default. You will be taxed as a sole proprietor unless you later file Form 8832 (C-corp) or 2553 (S-corp). Do NOT elect S-corp here without CPA review.",
        ),
        _step(
            "Reason for applying: Started a new business",
            "Pick 'Started a new business' from the list of reasons.",
            fields=[{"label": "Reason for applying", "value": "Started a new business"}],
        ),
        _step(
            "Responsible Party identification",
            "Enter your personal info as the Responsible Party. The IRS requires a real human - never list the LLC as its own Responsible Party.",
            fields=[
                {"label": "First name", "value": "Adam"},
                {"label": "Last name", "value": "Doherty"},
                {"label": "SSN or ITIN", "value": "your SSN (XXX-XX-XXXX)"},
                {"label": "I am the sole owner of the LLC", "value": "Yes"},
            ],
            gotcha="The Responsible Party MUST have an SSN or ITIN. There is no way around this for a US-resident LLC.",
        ),
        _step(
            "Business address",
            "Enter the LLC's principal business address. This is the address that appears on your Florida Articles of Organization.",
            fields=[
                {"label": "Street", "value": "your principal business address from Sunbiz filing"},
                {"label": "City", "value": "Jacksonville"},
                {"label": "State", "value": "Florida"},
                {"label": "ZIP", "value": "your ZIP"},
                {"label": "Phone", "value": "your phone number"},
            ],
            gotcha="If your business address is a home address, you will be giving up some privacy - the EIN confirmation letter goes to that address and the address can show up on later filings. Acceptable for a single-member home-based LLC; just know what you are picking.",
        ),
        _step(
            "LLC information",
            "Confirm the legal name and Florida document number from your Articles of Organization.",
            fields=[
                {"label": "Legal name of LLC", "value": "ADA AI LLC"},
                {"label": "Trade name / DBA", "value": "leave blank unless you registered one"},
                {"label": "County of LLC", "value": "Duval"},
                {"label": "State where LLC was organized", "value": "Florida"},
                {"label": "Start date of business", "value": "the date Sunbiz approved your filing"},
            ],
        ),
        _step(
            "Activity questions",
            "Answer honestly about what your business will do.",
            fields=[
                {"label": "Do you have or expect to have employees in the next 12 months?", "value": "No"},
                {"label": "Federal excise tax / gambling / alcohol / etc.", "value": "No (unless applicable)"},
                {"label": "What does the business primarily do?", "value": "Other"},
                {"label": "Describe activity", "value": "AI consulting and software development services"},
            ],
            gotcha="If you answer 'Yes' to employees, the IRS will start asking about Form 941 (employment taxes). For a single-member LLC with no payroll, the answer is No.",
        ),
        _step(
            "Choose how you want to receive the EIN letter",
            "Pick 'Receive letter online' to get the EIN immediately as a PDF. The mail option takes 4-6 weeks.",
            fields=[{"label": "How would you like to receive your EIN Confirmation Letter?", "value": "Receive letter online"}],
            gotcha="The PDF letter (Form CP 575) is THE evidence that this EIN exists. Save it now - the IRS does NOT email it to you and you cannot re-download it later. If you lose it you have to call the IRS Business & Specialty Tax Line (800-829-4933) for a replacement letter (Form 147C), which takes weeks.",
        ),
        _step(
            "Review and submit",
            "Verify every field on the summary page is exactly right. The EIN is permanent the moment you submit.",
            completion="You see a confirmation page with your new 9-digit EIN and a button to download Form CP 575 as a PDF.",
        ),
        _step(
            "Save the CP 575 confirmation PDF immediately",
            "Click 'Download' to save the CP 575 PDF. Save it to your secure company docs folder with a clear filename so future-you can find it.",
            completion="A file named something like 'ADA-AI-LLC-EIN-CP575-2026-05.pdf' lives in your company docs folder.",
        ),
        _step(
            "Record the EIN in Zero",
            "Come back to this task in Zero, paste the EIN into the description/links, mark this task complete, and answer Zero's completion-review question.",
            completion="Zero shows this task done and unlocks the 'Open business checking' and 'Apply for business credit card' tasks.",
        ),
    ],
    "evidence_to_archive": [
        "CP 575 confirmation letter (PDF) saved to your secure company docs folder.",
        "The EIN number itself recorded in Zero (in the task description, not in chat).",
        "Date issued and Responsible Party recorded for future CPA reference.",
    ],
    "what_this_unlocks": [
        "Open ADA AI LLC business checking account.",
        "Apply for one business credit card with reporting policy documented.",
        "Begin bookkeeping with AI/API spend categorized to the LLC.",
        "Issue 1099s to contractors if you ever hire one.",
        "File the LLC's federal return (Schedule C on your 1040 for a single-member LLC).",
    ],
    "common_mistakes": [
        "Paying $200+ to a third-party EIN service. The IRS gives EINs for free.",
        "Trying to apply before the LLC is approved by Florida - the IRS will reject it.",
        "Selecting S-corp election here without CPA review - that locks in payroll obligations.",
        "Closing the browser before downloading the CP 575 PDF.",
        "Listing the LLC itself as the Responsible Party - the IRS rejects this for single-member LLCs.",
    ],
    "if_something_goes_wrong": [
        "'Reference number 101' error: The IRS thinks the LLC name conflicts with an existing entity. Wait 48 hours after Sunbiz approval and try again.",
        "'Reference number 102/103/108/109': A field validation issue - re-check name spelling and SSN.",
        "If you submit but never get the PDF: Call IRS Business & Specialty Tax Line at 800-829-4933 (Mon-Fri 7am-7pm local) and request a 147C letter.",
    ],
    "completion_fields": [
        {"key": "ein", "label": "EIN (employer identification number)", "placeholder": "XX-XXXXXXX", "required": True, "sensitive": True, "domain": "Formation"},
        {"key": "ein_responsible_party", "label": "Responsible party on file", "placeholder": "Adam Doherty", "domain": "Formation"},
        {"key": "ein_cp575_path", "label": "Path or URL to CP 575 PDF", "placeholder": "C:\\code\\vault\\ObsidianZero\\...", "domain": "Formation"},
        {"key": "ein_issued_at", "label": "Date EIN was issued (YYYY-MM-DD)", "placeholder": "2026-05-12", "domain": "Formation"},
    ],
}


FLORIDA_LLC_WALKTHROUGH: dict[str, Any] = {
    "title": "File Florida LLC Articles of Organization on Sunbiz",
    "time_required": "30-45 minutes",
    "cost": "$125 ($100 filing fee + $25 registered agent designation) paid by credit card to the Florida Department of State.",
    "best_time": "Weekday business hours. Filings submitted overnight or on weekends still process the next business day.",
    "prerequisites": [
        "You ran a Florida Sunbiz name search and ADA AI LLC is available (no exact match).",
        "You ran a USPTO trademark search on ADA AI and there is no blocking federal mark.",
        "You decided your principal business address (home address is acceptable but will be public).",
        "You decided your registered agent. You can be your own registered agent if you have a Florida street address (not a PO box) and are willing to be served legal papers at that address during business hours.",
        "You have a credit or debit card for the $125 filing fee.",
    ],
    "steps": [
        _step(
            "Open the official Sunbiz LLC filing portal",
            "Use the .gov URL only. There are many lookalike scam sites.",
            url="https://dos.fl.gov/sunbiz/start-business/efile/fl-llc/",
            completion="You see the Florida Department of State 'eFile Limited Liability Company' page.",
        ),
        _step(
            "Click 'File a Limited Liability Company'",
            "Read the disclaimer, then click through to the filing form.",
            button="Start New Filing",
        ),
        _step(
            "Enter the LLC name",
            "Type the exact legal name. Florida requires an LLC designator at the end.",
            fields=[
                {"label": "Limited Liability Company Name", "value": "ADA AI LLC"},
            ],
            gotcha="Must include 'LLC', 'L.L.C.', or 'Limited Liability Company'. 'ADA AI' alone will be rejected.",
        ),
        _step(
            "Enter the principal place of business",
            "This is the LLC's main business address. It will be public record.",
            fields=[
                {"label": "Street Address", "value": "your principal business address"},
                {"label": "City", "value": "Jacksonville"},
                {"label": "State", "value": "FL"},
                {"label": "ZIP", "value": "your ZIP"},
            ],
        ),
        _step(
            "Enter the mailing address",
            "Same as principal address unless you want LLC mail going elsewhere (e.g., a PO box).",
        ),
        _step(
            "Designate a registered agent",
            "The registered agent is the person/company authorized to receive lawsuit papers for the LLC. Must have a Florida street address.",
            fields=[
                {"label": "Registered Agent Name", "value": "Adam Doherty (if self-serving) OR a registered-agent service"},
                {"label": "Florida Street Address", "value": "must be a real Florida street address, not a PO box"},
                {"label": "Registered Agent Signature", "value": "type your name to accept the role"},
            ],
            gotcha="If you are your own registered agent, your home address becomes the official service address. Process servers (and any junk-mail companies who scrape Sunbiz) can show up there. A $50-$150/year registered-agent service buys privacy.",
        ),
        _step(
            "Add managers/members",
            "List yourself as the sole member.",
            fields=[
                {"label": "Title", "value": "MGRM (manager and member)"},
                {"label": "Name", "value": "Adam Doherty"},
                {"label": "Address", "value": "your address"},
            ],
        ),
        _step(
            "Effective date (optional)",
            "Leave blank to make the LLC effective immediately. You can specify a future date (within 5 days before or 90 days after filing) if you need to align with a tax year.",
        ),
        _step(
            "Sign and pay",
            "Type your name to electronically sign as 'Authorized Person'. Submit payment.",
            fields=[
                {"label": "Signature of Authorized Person", "value": "Adam Doherty"},
                {"label": "Total fee", "value": "$125.00"},
            ],
        ),
        _step(
            "Save the filing confirmation",
            "Sunbiz emails a confirmation with your document number within minutes. The Articles of Organization PDF is available for download within 24-48 hours from sunbiz.org/Inquiry.",
            completion="You have a Florida document number (looks like L26000XXXXXX) and the approved Articles of Organization PDF saved to your secure company docs folder.",
        ),
    ],
    "evidence_to_archive": [
        "Florida Articles of Organization PDF (the approved version, not the submitted version).",
        "Document number recorded in Zero.",
        "Effective date and registered agent info recorded for renewal tracking.",
    ],
    "what_this_unlocks": [
        "Apply for EIN with the IRS (must wait for Florida approval first).",
        "Open business bank account.",
        "Sign operating agreement (you draft it yourself - Florida does not require filing it).",
        "Annual report due May 1 each following year ($138.75 fee or $538.75 with $400 late penalty after Sept 30).",
    ],
    "common_mistakes": [
        "Forgetting 'LLC' in the name (Florida will reject the filing).",
        "Using a PO box for the registered agent address.",
        "Paying a $500+ filing service for a $125 state fee.",
        "Skipping the registered agent's e-signature acceptance - filing will be rejected.",
    ],
    "completion_fields": [
        {"key": "florida_doc_number", "label": "Florida document number", "placeholder": "L26000XXXXXX", "required": True, "domain": "Formation"},
        {"key": "florida_filing_date", "label": "Effective filing date (YYYY-MM-DD)", "domain": "Formation"},
        {"key": "florida_articles_path", "label": "Path or URL to approved Articles of Organization PDF", "domain": "Formation"},
        {"key": "florida_principal_address", "label": "Principal business address on file", "domain": "Formation"},
        {"key": "florida_registered_agent_name", "label": "Registered agent name on filing", "domain": "Formation"},
    ],
}


BUSINESS_BANK_WALKTHROUGH: dict[str, Any] = {
    "title": "Open ADA AI LLC business checking account",
    "time_required": "60-90 minutes total: 30 min comparing banks, 30 min in-branch or online application, then 1-3 business days for the account to fund.",
    "cost": "Most options are free if you keep a small balance. Expect a $5-$15 monthly fee waivable with direct deposit or minimum balance.",
    "prerequisites": [
        "Florida LLC is approved (Articles of Organization PDF in hand).",
        "EIN confirmation letter (CP 575) saved.",
        "Operating Agreement signed (banks ask for it - you draft and sign it yourself for a single-member LLC).",
        "Your driver's license or passport.",
        "An initial deposit ($25-$500 depending on bank).",
    ],
    "steps": [
        _step(
            "Compare 3 business checking options",
            "Pick one of: Mercury (online, founder-friendly, no fees, great UX), Bluevine (online, 2% APY interest), Chase Business Complete (in-person, more ATMs but $15/mo unless $2k balance), or a Florida community bank if you want a local relationship.",
            completion="You decided which bank and recorded why in this task's notes.",
        ),
        _step(
            "Apply online OR walk into a branch",
            "Mercury and Bluevine are 100% online. Chase prefers in-branch for LLCs. Bring the documents in your prerequisites list.",
            url="https://mercury.com OR https://www.bluevine.com OR https://www.chase.com/business/banking",
        ),
        _step(
            "Provide LLC documentation",
            "Banks require: EIN letter, Articles of Organization, Operating Agreement, beneficial owner ID (your driver's license), and the LLC's address. They will scan everything.",
            gotcha="Banks must collect beneficial ownership info under FinCEN rules - they will ask for SSN and DOB even though the EIN belongs to the LLC. This is normal.",
        ),
        _step(
            "Sign signature card and beneficial ownership form",
            "You sign as 'Member' or 'Sole Member, ADA AI LLC' - never just 'Adam Doherty' for the LLC account.",
        ),
        _step(
            "Fund the account",
            "Initial deposit by ACH, wire, or check. Most banks want $25-$500.",
            completion="You see the new account in online banking with the deposit landed.",
        ),
        _step(
            "Set up online banking + categorization",
            "Enable 2FA. Create a strong unique password (use 1Password). Hook into QuickBooks or Wave when you set up bookkeeping. Print one statement and save the account/routing numbers in your secure docs.",
        ),
        _step(
            "Record account metadata in Zero (no secrets)",
            "In Zero, record: bank name, account type, opened date. Do NOT paste account numbers or passwords - secrets stay in 1Password.",
        ),
    ],
    "evidence_to_archive": [
        "Bank welcome letter and first statement (proves account exists for IRS audits).",
        "Voided check or account info sheet (for setting up ACH).",
        "Account number stored ONLY in 1Password, not in Zero or git.",
    ],
    "what_this_unlocks": [
        "Apply for one business credit card (separate task).",
        "Receive client payments via Stripe/ACH/wire.",
        "Pay business expenses (cloud, SaaS, contractors) from a clearly-separate account.",
        "Bookkeeping reconciliation has a single source of truth.",
    ],
    "common_mistakes": [
        "Using a personal account 'just for now' - this destroys LLC liability protection (called 'piercing the corporate veil').",
        "Mixing personal and business transactions - one accidental purchase can blow up your audit defense.",
        "Choosing a bank with high minimum balance requirements when you have no revenue yet.",
    ],
    "completion_fields": [
        {"key": "business_bank_name", "label": "Bank name", "placeholder": "Mercury", "required": True, "domain": "Finance"},
        {"key": "business_bank_account_last4", "label": "Account number (last 4 only)", "placeholder": "1234", "sensitive": True, "domain": "Finance"},
        {"key": "business_bank_routing_last4", "label": "Routing number (last 4 only)", "placeholder": "5678", "sensitive": True, "domain": "Finance"},
        {"key": "business_bank_opened_at", "label": "Account opened on (YYYY-MM-DD)", "domain": "Finance"},
        {"key": "business_bank_signatory", "label": "Signatory title used on the account", "placeholder": "Sole Member, ADA AI LLC", "domain": "Finance"},
    ],
}


BUSINESS_CREDIT_CARD_WALKTHROUGH: dict[str, Any] = {
    "title": "Apply for one business credit card with documented reporting policy",
    "time_required": "30 minutes",
    "cost": "Annual fee $0-$95 depending on card. Hard credit pull will drop your personal score 5-10 points for ~3 months.",
    "prerequisites": [
        "EIN confirmation letter.",
        "Business checking account open and funded.",
        "Personal FICO score known (use creditkarma.com if you don't know it).",
        "Decision recorded on whether you want a card that reports to PERSONAL bureaus or only BUSINESS bureaus.",
    ],
    "steps": [
        _step(
            "Document the reporting-policy decision FIRST",
            "Critical: cards report differently. Most business cards (Chase Ink, Amex, Capital One Spark) report only to BUSINESS bureaus unless you default - meaning utilization will not hurt your personal FICO. Some (Capital One specifically) report to personal bureaus regardless. Look up your candidate card on doctorofcredit.com to confirm its reporting policy before you apply. Record the decision in this task.",
            url="https://www.doctorofcredit.com/which-business-credit-cards-report-to-personal-credit/",
            completion="Reporting policy for your chosen card is documented in this task with a source link.",
        ),
        _step(
            "Pick one card and apply",
            "Top picks for a new LLC: Chase Ink Business Cash ($0 fee, 5% on telecom/office supplies, $750 bonus after $6k spend), Amex Business Gold ($295 fee, 4x on top-2 categories, only worth it at $50k+/yr spend), Capital One Spark Cash Plus ($150 fee but 2% flat). For a Year-1 LLC with low spend: Chase Ink Cash is the right answer.",
            url="https://creditcards.chase.com/business-credit-cards/ink/cash",
        ),
        _step(
            "Fill the application",
            "Use your LLC info but you will personally guarantee the card.",
            fields=[
                {"label": "Legal business name", "value": "ADA AI LLC"},
                {"label": "Business EIN", "value": "your EIN from CP 575"},
                {"label": "Business address", "value": "principal business address from Sunbiz"},
                {"label": "Business start date", "value": "Florida approval date"},
                {"label": "Business type", "value": "Limited Liability Company (LLC)"},
                {"label": "Industry", "value": "Information / Professional Services"},
                {"label": "Annual business revenue", "value": "estimated (be conservative, do not lie)"},
                {"label": "Annual personal income", "value": "your real personal income - they cross-check"},
                {"label": "Authorized signer", "value": "Adam Doherty"},
            ],
            gotcha="Personal guarantee is required for nearly every small-business card. If you default, they come after your personal assets. The card limit is based on your PERSONAL credit, not the LLC's.",
        ),
        _step(
            "Wait for approval",
            "Most issuers respond in 60 seconds. If 'pending', call reconsideration line - usually you can talk them into approval if your personal credit is good.",
        ),
        _step(
            "Activate, set up autopay",
            "Activate the physical card. Set up autopay-full-balance from your business checking. This eliminates 99% of fee/interest exposure.",
            completion="Card is in your wallet, autopay is on full-statement, and you have not put a single personal charge on it.",
        ),
        _step(
            "Record metadata in Zero",
            "Card type, last 4 digits, autopay configured, reporting policy. NOT the full number or CVV.",
        ),
    ],
    "evidence_to_archive": [
        "Card terms and conditions PDF.",
        "Reporting policy decision document.",
        "Autopay confirmation screenshot.",
    ],
    "what_this_unlocks": [
        "Pay AI/cloud/SaaS bills cleanly from a business card with cashback or points.",
        "Build LLC credit history with Dun & Bradstreet via the issuer's reporting.",
        "Separate business expenses from personal in one place.",
    ],
    "common_mistakes": [
        "Using a card that reports to personal bureaus when you wanted business-only.",
        "Applying for 3+ cards at once (too many hard pulls).",
        "Putting personal charges on the business card - destroys LLC separation.",
    ],
    "completion_fields": [
        {"key": "business_card_issuer", "label": "Card issuer", "placeholder": "Chase", "required": True, "domain": "Finance"},
        {"key": "business_card_product", "label": "Card product name", "placeholder": "Ink Business Cash", "domain": "Finance"},
        {"key": "business_card_last4", "label": "Card number (last 4 only)", "sensitive": True, "domain": "Finance"},
        {"key": "business_card_reporting_policy", "label": "Reporting policy (business bureaus only / personal too)", "domain": "Finance"},
        {"key": "business_card_autopay", "label": "Autopay configured (full statement / minimum / off)", "domain": "Finance"},
    ],
}


REGISTERED_AGENT_WALKTHROUGH: dict[str, Any] = {
    "title": "Choose registered agent for ADA AI LLC",
    "time_required": "15 minutes",
    "cost": "$0 (be your own RA) OR $50-$150/year (service).",
    "prerequisites": ["LLC name decided. Florida address available."],
    "steps": [
        _step(
            "Decide: self-serve or pay a service",
            "Self-serve saves $50-$150/year but your address becomes public record AND you must be available at that address during business hours to accept lawsuit papers. A service buys privacy and forwarding.",
        ),
        _step(
            "If service: pick one",
            "Northwest Registered Agent ($125/year, founder-favorite, no upsells, can use their address as your principal address for some filings) is the typical pick. Avoid LegalZoom and IncFile - they upsell aggressively.",
            url="https://www.northwestregisteredagent.com/",
        ),
        _step(
            "Record the decision in Zero",
            "Note the agent name, the address that will appear on Florida filings, and the renewal date.",
        ),
    ],
    "evidence_to_archive": ["Registered agent agreement OR self-designation note with FL address."],
    "what_this_unlocks": ["You can complete the Sunbiz LLC filing."],
    "completion_fields": [
        {"key": "registered_agent_kind", "label": "Self-serve or paid service", "placeholder": "self / service", "required": True, "domain": "Formation"},
        {"key": "registered_agent_name", "label": "Registered agent name", "placeholder": "Adam Doherty OR Northwest Registered Agent Inc.", "domain": "Formation"},
        {"key": "registered_agent_address", "label": "Registered agent Florida address", "domain": "Formation"},
        {"key": "registered_agent_renewal_at", "label": "Next renewal date (YYYY-MM-DD)", "domain": "Formation"},
    ],
}


OPERATING_AGREEMENT_WALKTHROUGH: dict[str, Any] = {
    "title": "Draft and sign single-member LLC Operating Agreement",
    "time_required": "1-2 hours",
    "cost": "$0 if you use a template. $200-$500 if you have an attorney review (recommended once but not blocking).",
    "prerequisites": ["LLC formed and EIN issued."],
    "steps": [
        _step(
            "Use a Florida single-member LLC template",
            "Northwest Registered Agent and the Florida Bar both publish free templates. Avoid LegalZoom for templates - they push paid upsells in the doc itself.",
            url="https://www.northwestregisteredagent.com/llc/single-member-operating-agreement",
        ),
        _step(
            "Fill in the LLC-specific fields",
            "Legal name, EIN, formation date, principal address, member name, capital contribution amount (can be $0), management structure (member-managed), tax election (disregarded entity by default).",
        ),
        _step(
            "Sign and notarize (optional)",
            "Florida does not require notarization for a single-member LLC OA, but banks sometimes ask for it. Notary services are $10 at any UPS Store.",
        ),
        _step(
            "Save in company docs",
            "Store the signed PDF in the company docs folder. Banks will ask to see it when opening accounts.",
        ),
    ],
    "evidence_to_archive": ["Signed Operating Agreement PDF."],
    "what_this_unlocks": ["Banks will open the business checking account. Attorney can review IP assignment with this OA as context."],
    "completion_fields": [
        {"key": "operating_agreement_path", "label": "Path or URL to signed Operating Agreement PDF", "required": True, "domain": "Legal"},
        {"key": "operating_agreement_signed_at", "label": "Date signed (YYYY-MM-DD)", "domain": "Legal"},
        {"key": "operating_agreement_notarized", "label": "Notarized? (yes / no)", "domain": "Legal"},
    ],
}


BUSINESS_EMAIL_WALKTHROUGH: dict[str, Any] = {
    "title": "Set up business email at the company domain",
    "time_required": "45 minutes",
    "cost": "$6-$14/month for Google Workspace or Microsoft 365 (per user).",
    "prerequisites": ["You own a domain (adamdoherty.com or adappliedai.com or similar)."],
    "steps": [
        _step(
            "Pick provider: Google Workspace or Microsoft 365",
            "Google Workspace is the default for most small businesses. $6/user/month for Business Starter (good enough). Microsoft 365 is $6/user/month for Business Basic (Office apps, OneDrive). Google's spam filter is better.",
            url="https://workspace.google.com/business/signup/welcome",
        ),
        _step(
            "Verify domain ownership",
            "Add a TXT record at your DNS provider (Cloudflare, Namecheap, etc.). Google's wizard shows the exact record.",
        ),
        _step(
            "Create core aliases",
            "Create adam@, hello@, contact@, support@, billing@, legal@. Set hello@ as primary inbox; route others to hello@ initially.",
        ),
        _step(
            "Configure SPF, DKIM, DMARC",
            "Add three DNS records: SPF (include _spf.google.com), DKIM (Google provides the value), DMARC (start with p=none, monitor). This stops spammers from spoofing your domain.",
            gotcha="If you skip DKIM/DMARC, your outbound email lands in spam folders. This is the #1 reason new business email looks broken.",
        ),
        _step(
            "Enable 2FA and store the recovery codes",
            "Critical: a hijacked business email = hijacked LLC. Use a hardware key (YubiKey) or at minimum a TOTP app like 1Password.",
        ),
    ],
    "evidence_to_archive": ["Domain ownership proof. DNS configuration screenshot. 2FA recovery codes in 1Password."],
    "what_this_unlocks": ["You can put a real email on the website. Customers and contractors get a professional contact. Filing and bank forms route to the right inbox."],
    "completion_fields": [
        {"key": "business_email_provider", "label": "Provider", "placeholder": "Google Workspace", "required": True, "domain": "Operations"},
        {"key": "business_email_domain", "label": "Business email domain", "placeholder": "adappliedai.com", "required": True, "domain": "Operations"},
        {"key": "business_email_primary", "label": "Primary inbox address", "placeholder": "hello@adappliedai.com", "domain": "Operations"},
        {"key": "business_email_aliases", "label": "Aliases configured (comma separated)", "domain": "Operations"},
        {"key": "business_email_2fa", "label": "2FA method", "placeholder": "YubiKey + 1Password TOTP backup", "domain": "Operations"},
    ],
}


ASSET_TRANSFER_WALKTHROUGH: dict[str, Any] = {
    "title": "Transfer existing equipment to ADA AI LLC at fair market value",
    "time_required": "2-3 hours for the packet, plus 1 CPA consult.",
    "cost": "$0 in cash, but you may transfer thousands of dollars in equipment value. CPA consult is $200-$500.",
    "prerequisites": ["LLC formed, EIN issued, bookkeeping basics in place.", "Inventory of equipment you currently own personally that will be used by the LLC."],
    "steps": [
        _step(
            "List every asset to transfer",
            "Workstation, monitors, GPU, peripherals, robot hardware, office furniture, software licenses. For each: original purchase date, original cost (if you have receipts), current condition, photos.",
        ),
        _step(
            "Determine FMV (fair market value) for each asset",
            "Use eBay sold listings, B&H Photo used-condition prices, or a written third-party appraisal for big items. FMV is what a willing buyer would pay today, NOT what you paid originally. A 3-year-old workstation that cost $4,000 might be worth $1,200 today.",
            gotcha="Do NOT use original purchase price. The IRS audits on FMV. Inflating FMV is tax fraud; understating FMV is leaving deductions on the table.",
        ),
        _step(
            "Draft the Owner Equipment Transfer Memo",
            "Use the template at docs/company/templates/owner-equipment-transfer-memo.md. Each asset gets a row: description, serial number, FMV, FMV source (eBay link or appraisal), date placed in service for the LLC, business-use percentage.",
        ),
        _step(
            "Decide: capital contribution or sale",
            "Two options. (a) Capital contribution: you contribute the equipment to the LLC at FMV, no money changes hands, you get FMV as your capital basis. (b) Sale to LLC: the LLC pays you cash for the equipment. Most single-member LLCs do (a) because it's simpler and the LLC has no cash. Talk to a CPA before doing (b).",
        ),
        _step(
            "CPA review BEFORE finalizing",
            "Required. The asset transfer affects depreciation, your basis in the LLC, and possibly self-employment tax. A 30-minute call with a CPA is $100-$200 and prevents a 5-figure mistake.",
        ),
        _step(
            "Record in books and Zero",
            "Once approved, the LLC books show each asset as a depreciable fixed asset. Zero tracks the memo as completed evidence.",
        ),
    ],
    "evidence_to_archive": [
        "Transfer memo PDF signed and dated.",
        "Photos of every item.",
        "FMV source links (eBay listings, appraisal letters).",
        "CPA review note.",
    ],
    "what_this_unlocks": [
        "Depreciation deductions on Schedule C.",
        "Clean asset register for insurance.",
        "Clear separation of personal vs business property.",
    ],
    "completion_fields": [
        {"key": "asset_transfer_memo_path", "label": "Path or URL to signed Owner Equipment Transfer Memo", "required": True, "domain": "Finance"},
        {"key": "asset_transfer_total_fmv", "label": "Total FMV transferred (USD)", "placeholder": "$3,250", "domain": "Finance"},
        {"key": "asset_transfer_structure", "label": "Capital contribution or sale to LLC", "placeholder": "capital_contribution", "domain": "Finance"},
        {"key": "asset_transfer_placed_in_service_on", "label": "Date placed in service for the LLC (YYYY-MM-DD)", "domain": "Finance"},
        {"key": "asset_transfer_cpa_reviewer", "label": "CPA who reviewed (name + firm)", "domain": "Finance"},
    ],
}


IP_ASSIGNMENT_WALKTHROUGH: dict[str, Any] = {
    "title": "Draft software/IP assignment schedule from Adam to ADA AI LLC",
    "time_required": "2-3 hours for the draft, plus 1 attorney review.",
    "cost": "$300-$800 for attorney review (one-time).",
    "prerequisites": ["LLC formed.", "List of repositories and software you wrote personally that the LLC will use commercially."],
    "steps": [
        _step(
            "Inventory the IP",
            "List every repo, codebase, model, dataset, and brand asset (logos, copy, designs) you personally created. For each: name, public repo URL (if any), license currently applied, dependencies, whether it has any third-party contributions.",
        ),
        _step(
            "Use the template at docs/company/templates/ip-assignment-schedule.md",
            "Fill in each asset row with: description, creation date, current owner (you), assignee (ADA AI LLC), consideration (often $1 plus services-as-employee), effective date.",
        ),
        _step(
            "Decide: assignment vs license",
            "Assignment transfers ownership fully to the LLC (clean for fundraising or sale). License keeps you as owner but grants the LLC perpetual rights (better if you want optionality to use the IP outside the LLC). For most single-founder LLCs: assignment is cleaner.",
        ),
        _step(
            "Get attorney review BEFORE signing",
            "Required. IP assignments are easy to do wrong and impossible to undo without paying a lawyer twice. Find a startup-focused attorney; expect 1-2 hours billed at $200-$400/hr.",
        ),
        _step(
            "Sign and record",
            "Both as 'Adam Doherty, assignor' and 'Adam Doherty, sole member of ADA AI LLC, assignee'. Date it. Save the signed PDF.",
        ),
    ],
    "evidence_to_archive": ["Signed assignment schedule PDF.", "Attorney review note.", "Updated repo READMEs that say 'Copyright ADA AI LLC' for assigned repos."],
    "what_this_unlocks": ["Clean cap table for any future fundraising or acquisition.", "LLC can license the IP to clients or sell it.", "Separates Adam-personal IP from LLC IP cleanly."],
    "completion_fields": [
        {"key": "ip_assignment_path", "label": "Path or URL to signed IP Assignment Schedule PDF", "required": True, "domain": "Legal"},
        {"key": "ip_assignment_structure", "label": "Assignment or license", "placeholder": "assignment", "domain": "Legal"},
        {"key": "ip_assignment_effective_date", "label": "Effective date (YYYY-MM-DD)", "domain": "Legal"},
        {"key": "ip_assignment_attorney", "label": "Reviewing attorney (name + firm)", "domain": "Legal"},
        {"key": "ip_assignment_assets_count", "label": "Number of assets in schedule", "domain": "Legal"},
    ],
}


SUNBIZ_NAME_CHECK_WALKTHROUGH: dict[str, Any] = {
    "title": "Verify ADA AI LLC name availability on Sunbiz + USPTO",
    "time_required": "20 minutes",
    "cost": "Free",
    "prerequisites": [],
    "steps": [
        _step(
            "Search Florida Sunbiz for exact and similar names",
            "Open the Sunbiz business name search. Search 'ADA AI', 'Adam Doherty Applied AI', and 2-3 close variants. Record every hit (URL + status) in this task.",
            url="https://search.sunbiz.org/Inquiry/CorporationSearch/ByName",
        ),
        _step(
            "Search USPTO for federal trademarks",
            "Open the USPTO TESS search. Search 'ADA AI' for any live mark in software / AI services (classes 9, 35, 42). A live registered mark = stop; a pending application = caution; an abandoned mark = ok.",
            url="https://tmsearch.uspto.gov/",
        ),
        _step(
            "Decide and record",
            "Write your go/no-go decision in this task with the search URLs as evidence. If go: this unlocks the Florida LLC filing.",
        ),
    ],
    "evidence_to_archive": ["Screenshots or URLs of Sunbiz and USPTO search results.", "Go/no-go decision note."],
    "what_this_unlocks": ["Florida LLC filing on Sunbiz."],
    "completion_fields": [
        {"key": "sunbiz_name_decision", "label": "Go or no-go", "placeholder": "go", "required": True, "domain": "Formation"},
        {"key": "sunbiz_chosen_name", "label": "Chosen legal name", "placeholder": "ADA AI LLC", "domain": "Formation"},
        {"key": "sunbiz_uspto_status", "label": "USPTO finding summary", "placeholder": "no blocking live marks in classes 9/35/42", "domain": "Formation"},
        {"key": "sunbiz_search_evidence_url", "label": "Path or URL to search evidence", "domain": "Formation"},
    ],
}


WALKTHROUGHS: dict[str, dict[str, Any]] = {
    "ein": EIN_WALKTHROUGH,
    "florida_llc": FLORIDA_LLC_WALKTHROUGH,
    "sunbiz_name": SUNBIZ_NAME_CHECK_WALKTHROUGH,
    "registered_agent": REGISTERED_AGENT_WALKTHROUGH,
    "operating_agreement": OPERATING_AGREEMENT_WALKTHROUGH,
    "business_bank": BUSINESS_BANK_WALKTHROUGH,
    "business_credit_card": BUSINESS_CREDIT_CARD_WALKTHROUGH,
    "business_email": BUSINESS_EMAIL_WALKTHROUGH,
    "asset_transfer": ASSET_TRANSFER_WALKTHROUGH,
    "ip_assignment": IP_ASSIGNMENT_WALKTHROUGH,
}


_MATCHERS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bapply for .*ein|\bget .*ein|\bein .*irs|\bcp ?575|employer identification", re.I), "ein"),
    (re.compile(r"file .*florida llc|articles of organization|sunbiz.*file|llc .*filing", re.I), "florida_llc"),
    (re.compile(r"verify .*name|sunbiz.*name|name .*availability|trademark .*search|uspto", re.I), "sunbiz_name"),
    (re.compile(r"registered agent", re.I), "registered_agent"),
    (re.compile(r"operating agreement", re.I), "operating_agreement"),
    (re.compile(r"business checking|business bank|open .*bank|open .*checking", re.I), "business_bank"),
    (re.compile(r"credit card|business card|card .*policy|card .*application", re.I), "business_credit_card"),
    (re.compile(r"business email|google workspace|email .*domain|domain .*email|dns .*email", re.I), "business_email"),
    (re.compile(r"asset transfer|equipment .*transfer|fmv|fair market value|equipment .*fmv", re.I), "asset_transfer"),
    (re.compile(r"ip assignment|software.?ip|ip .*schedule|intellectual property", re.I), "ip_assignment"),
]


def walkthrough_for(title: str, description: str = "") -> Optional[dict[str, Any]]:
    """Return the structured walkthrough for a task, or None if no curated match."""
    haystack = f"{title or ''} {description or ''}"
    for pattern, key in _MATCHERS:
        if pattern.search(haystack):
            return WALKTHROUGHS[key]
    return None


def walkthrough_keys() -> list[str]:
    return sorted(WALKTHROUGHS.keys())
