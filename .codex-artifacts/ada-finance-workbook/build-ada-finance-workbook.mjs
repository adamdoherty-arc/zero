import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const rootDir = "C:/code/zero";
const outputDir = path.join(rootDir, "docs/company/finance");
const previewDir = path.join(rootDir, ".codex-artifacts/ada-finance-workbook/previews");
const outputPath = path.join(outputDir, "ada-ai-llc-finance-setup-workbook.xlsx");

await fs.mkdir(outputDir, { recursive: true });
await fs.mkdir(previewDir, { recursive: true });

const workbook = Workbook.create();
const navy = "#1E3A5F";
const blue = "#2563EB";
const green = "#0F766E";
const amber = "#B45309";
const gray = "#111827";
const lightFill = "#EFF6FF";
const paleGreen = "#ECFDF5";
const paleAmber = "#FFFBEB";
const border = "#CBD5E1";

function colName(index) {
  let n = index;
  let name = "";
  while (n > 0) {
    const rem = (n - 1) % 26;
    name = String.fromCharCode(65 + rem) + name;
    n = Math.floor((n - 1) / 26);
  }
  return name;
}

function rangeAddress(col, row, rows, cols) {
  const start = `${colName(col)}${row}`;
  const end = `${colName(col + cols - 1)}${row + rows - 1}`;
  return rows === 1 && cols === 1 ? start : `${start}:${end}`;
}

function writeBlock(sheet, col, row, data) {
  sheet.getRange(rangeAddress(col, row, data.length, data[0].length)).values = data;
}

function setWidths(sheet, widths) {
  widths.forEach((width, index) => {
    sheet.getRange(`${colName(index + 1)}:${colName(index + 1)}`).format.columnWidth = width;
  });
}

function styleHeader(sheet, address) {
  sheet.getRange(address).format = {
    fill: navy,
    font: { bold: true, color: "#FFFFFF" },
    wrapText: true,
    borders: { bottom: { color: "#FFFFFF", style: "continuous" } },
  };
}

function styleTable(sheet, headerAddress, bodyAddress) {
  styleHeader(sheet, headerAddress);
  sheet.getRange(bodyAddress).format = {
    borders: {
      insideHorizontal: { color: border, style: "continuous" },
      insideVertical: { color: border, style: "continuous" },
      outline: { color: border, style: "continuous" },
    },
    wrapText: true,
  };
}

function title(sheet, text, subtitle, lastCol) {
  writeBlock(sheet, 1, 1, [[text]]);
  writeBlock(sheet, 1, 2, [[subtitle]]);
  sheet.getRange(rangeAddress(1, 1, 1, lastCol)).format = {
    fill: navy,
    font: { bold: true, color: "#FFFFFF", size: 16 },
  };
  sheet.getRange(rangeAddress(1, 2, 1, lastCol)).format = {
    fill: lightFill,
    font: { color: "#1F2937", italic: true },
    wrapText: true,
  };
}

function addTable(sheet, startCol, startRow, headers, rows) {
  writeBlock(sheet, startCol, startRow, [headers, ...rows]);
  const full = rangeAddress(startCol, startRow, rows.length + 1, headers.length);
  const header = rangeAddress(startCol, startRow, 1, headers.length);
  styleTable(sheet, header, full);
}

const dashboard = workbook.worksheets.add("Dashboard");
title(dashboard, "ADA AI LLC Finance Setup Dashboard", "EIN, bank, card, books, home-office, assets, robot, and IP setup tracker. Human approval and CPA/attorney review still control final actions.", 11);
setWidths(dashboard, [22, 18, 18, 18, 18, 18, 18, 20, 4, 16, 12, 4, 18, 18, 18, 18, 18, 18, 18, 18]);
writeBlock(dashboard, 1, 4, [
  ["Metric", "Value", "Source"],
  ["Setup items complete", "=COUNTIF('Setup Checklist'!D3:D20,\"Done\")", "Setup Checklist"],
  ["Open high-risk approvals", "=COUNTIF('Setup Checklist'!C3:C20,\"High\")-COUNTIFS('Setup Checklist'!C3:C20,\"High\",'Setup Checklist'!D3:D20,\"Done\")", "Setup Checklist"],
  ["Tracked monthly subscriptions", "=SUM(Subscriptions!D3:D60)", "Subscriptions"],
  ["Annualized subscriptions", "=SUM(Subscriptions!G3:G60)", "Subscriptions"],
  ["Asset FMV pending count", "=COUNTIF(Assets!H3:H80,\"Missing\")", "Assets"],
  ["Potential home-office actual allocation", "='Home Office'!E21", "Home Office"],
  ["CPA packet ready items", "=COUNTIF('CPA Packet'!D3:D60,\"Ready\")", "CPA Packet"],
]);
styleTable(dashboard, "A4:C4", "A4:C11");
dashboard.getRange("B7:B8").format.numberFormat = "$#,##0";
dashboard.getRange("B4:B11").format = { fill: paleGreen, font: { bold: true }, borders: { outline: { color: border, style: "continuous" } } };

writeBlock(dashboard, 5, 4, [
  ["Immediate Order", "Owner", "Approval Gate"],
  ["Confirm no EIN exists", "Adam / Finance", "Human"],
  ["Apply through free IRS EIN assistant", "Adam", "Human"],
  ["Open checking with EIN and formation packet", "Adam / Finance", "Human"],
  ["Document card reporting policy before applying", "Adam / Finance", "Human"],
  ["Start books and attach receipts", "Finance", "Internal"],
  ["Build equipment FMV transfer packet", "Finance / Asset", "CPA"],
  ["Draft software/IP schedule", "Legal", "Attorney + CPA"],
]);
styleTable(dashboard, "E4:G4", "E4:G11");

writeBlock(dashboard, 10, 3, [
  ["Status", "Count"],
  ["Done", "=COUNTIF('Setup Checklist'!D3:D20,J4)"],
  ["Ready", "=COUNTIF('Setup Checklist'!D3:D20,J5)"],
  ["Blocked", "=COUNTIF('Setup Checklist'!D3:D20,J6)"],
  ["In progress", "=COUNTIF('Setup Checklist'!D3:D20,J7)"],
]);
styleTable(dashboard, "J3:K3", "J3:K7");
const statusChart = dashboard.charts.add("bar", dashboard.getRange("J3:K7"));
statusChart.title = "Setup Status";
statusChart.hasLegend = false;
statusChart.xAxis = { axisType: "textAxis" };
statusChart.yAxis = { numberFormatCode: "0" };
statusChart.setPosition("M3", "T18");

const setup = workbook.worksheets.add("Setup Checklist");
title(setup, "ADA AI LLC Setup Checklist", "Sequence work here; do not mark gated actions done until the human approval and professional review columns are satisfied.", 9);
setWidths(setup, [26, 20, 12, 14, 36, 34, 18, 18, 34]);
addTable(setup, 1, 4,
  ["Step", "Owner", "Risk", "Status", "Evidence Required", "Record Location", "Approval", "Target", "Notes"],
  [
    ["Confirm no EIN already exists", "Finance", "High", "Ready", "Search secure ADA company records and email", "Secure company docs", "Adam", "2026-05-06", "Do this before applying."],
    ["Apply for EIN", "Adam", "High", "Blocked", "IRS confirmation letter / CP 575", "Secure company docs", "Adam", "2026-05-07", "Use IRS assistant directly; free."],
    ["Sign operating agreement", "Legal", "Critical", "Ready", "Signed operating agreement", "Legal docs", "Adam", "2026-05-09", "Needed for clean bank packet."],
    ["Open business checking", "Finance", "High", "Blocked", "EIN, articles, operating agreement, ID, ownership memo", "Bank/card decision log", "Adam", "2026-05-10", "First deposit classified as owner contribution."],
    ["Document business card policy", "Finance", "High", "Ready", "Personal guarantee, hard pull, reporting, fees, autopay", "Bank/card decision log", "Adam", "2026-05-11", "Minimize personal credit impact."],
    ["Start separate books", "Finance", "Medium", "In progress", "Chart of accounts and receipt intake", "Transactions / Subscriptions", "Internal", "2026-05-08", "AI/API spend gets its own category."],
    ["Home-office worksheet", "Finance", "Medium", "In progress", "Measurements, photos, utilities, internet, insurance, repairs", "Home Office", "CPA", "2026-05-12", "CPA decides simplified vs actual."],
    ["Existing equipment transfer packet", "Asset", "High", "In progress", "Serials, photos, receipts, upgrades, business-use %, FMV comparables", "Assets", "CPA", "2026-05-12", "No unsupported markup."],
    ["Robot purchase/transfer record", "Robotics", "High", "Ready", "Invoice or FMV memo, warranty, serial, purpose, location", "Assets", "Adam + CPA", "2026-05-13", "Buy directly from ADA when possible."],
    ["Software/IP schedule", "Legal", "Critical", "Ready", "Repo list, modules, dependencies, assignment/license scope", "IP & Software", "Attorney + CPA", "2026-05-13", "Unpaid development time is not basis."],
    ["First CPA packet", "Finance", "High", "Ready", "P&L, receipts, subscriptions, asset register, home office, questions", "CPA Packet", "CPA", "2026-06-15", "Use CPA agenda template."],
  ]);

const transactions = workbook.worksheets.add("Transactions");
title(transactions, "Transaction And Receipt Intake", "Enter each ADA transaction or owner-paid reimbursement candidate. Business amount is formula-driven from amount and business-use percent.", 10);
setWidths(transactions, [14, 24, 24, 14, 14, 16, 18, 34, 38, 16]);
addTable(transactions, 1, 4,
  ["Date", "Vendor", "Category", "Amount", "Business Use %", "Business Amount", "Paid From", "Receipt Link", "Business Purpose", "CPA Review"],
  [
    ["", "OpenAI / API", "AI/API spend", "", 1, "", "ADA card", "", "Model/API usage for ADA AI LLC development", "No"],
    ["", "Anthropic / coding", "AI/API spend", "", 1, "", "ADA card", "", "Coding assistant for ADA software work", "No"],
    ["", "Cloud or hosting", "Cloud and hosting", "", 1, "", "ADA bank/card", "", "Infrastructure for ADA products", "No"],
    ["", "Robot vendor", "Robot/equipment", "", 1, "", "ADA bank/card", "", "Robot hardware for ADA robotics lab", "Yes"],
    ["", "Owner reimbursement", "Owner reimbursement", "", "", "", "Owner paid", "", "Pre-bank ADA business expense candidate", "Yes"],
  ]);
transactions.getRange("F5:F104").formulas = Array.from({ length: 100 }, (_, index) => {
  const row = index + 5;
  return [`=IF(OR(D${row}="",E${row}=""),"",D${row}*E${row})`];
});
transactions.getRange("D5:F104").format.numberFormat = "$#,##0.00";
transactions.getRange("E5:E104").format.numberFormat = "0%";

const subscriptionsSheet = workbook.worksheets.add("Subscriptions");
title(subscriptionsSheet, "Subscription Register", "Track monthly AI, software, cloud, and bookkeeping spend with receipt evidence and business-use percentage.", 9);
setWidths(subscriptionsSheet, [24, 22, 18, 14, 14, 16, 16, 18, 30]);
addTable(subscriptionsSheet, 1, 4,
  ["Vendor", "Category", "Owner", "Monthly Cost", "Business Use %", "Renewal", "Annual Business Cost", "Evidence", "Notes"],
  [
    ["OpenAI", "AI platform", "LLM Ops", 20, 1, "Monthly", "", "Partial", "Move to ADA card after banking."],
    ["Anthropic", "AI coding", "Engineering", 20, 1, "Monthly", "", "Partial", "Move to ADA card after banking."],
    ["Google Gemini / AI Studio", "AI platform", "LLM Ops", 0, 1, "Usage-based", "", "Missing", "Record API invoices once paid."],
    ["GitHub", "Source control", "Engineering", 10, 1, "Monthly", "", "Ready", "Attach monthly receipt."],
    ["Google Workspace", "Business email", "Admin", 14, 1, "Monthly", "", "Missing", "Open after bank/email decision."],
    ["QuickBooks / Wave decision", "Bookkeeping", "Finance", 30, 1, "TBD", "", "Missing", "CPA should approve tool and account mapping."],
    ["Cloud / VPS / storage", "Infrastructure", "Engineering", 0, 1, "Usage-based", "", "Missing", "Add each provider."],
    ["Legion local stack", "Internal platform", "Engineering", 0, 1, "Self-hosted", "", "Ready", "Track hardware/cloud inputs separately."],
  ]);
subscriptionsSheet.getRange("G5:G64").formulas = Array.from({ length: 60 }, (_, index) => {
  const row = index + 5;
  return [`=IF(OR(D${row}="",E${row}=""),"",D${row}*12*E${row})`];
});
subscriptionsSheet.getRange("D5:D64").format.numberFormat = "$#,##0.00";
subscriptionsSheet.getRange("E5:E64").format.numberFormat = "0%";
subscriptionsSheet.getRange("G5:G64").format.numberFormat = "$#,##0.00";

const assetsSheet = workbook.worksheets.add("Assets");
title(assetsSheet, "Asset Register And Transfer Packet", "Use documented FMV only. Upgrades and configuration support value only when comparable market evidence supports it.", 12);
setWidths(assetsSheet, [24, 20, 18, 18, 18, 16, 16, 14, 18, 18, 18, 32]);
addTable(assetsSheet, 1, 4,
  ["Asset", "Type", "Current Owner", "Serial / ID", "Original Cost", "Upgrade Cost", "Current FMV", "FMV Evidence", "Business Use %", "Business Basis", "Transfer Method", "Notes"],
  [
    ["Main AI workstation", "Computer hardware", "Adam", "", "", "", "", "Partial", 0.9, "", "Owner contribution / bill of sale", "Add photos, specs, serials, receipts, comparables."],
    ["Monitors and peripherals", "Computer hardware", "Adam", "", "", "", "", "Missing", 0.9, "", "Owner contribution / bill of sale", "List each item with serial where available."],
    ["Upgraded components", "Computer components", "Adam", "", "", "", "", "Missing", 0.9, "", "Owner contribution / bill of sale", "GPU/RAM/storage upgrades need receipts and comparables."],
    ["Robot hardware", "Robot/equipment", "Adam or ADA", "", "", "", "", "Missing", 1, "", "ADA purchase / FMV transfer", "ADA buys directly when possible."],
    ["Robot-control software", "Software/IP", "Adam", "", "", "", "", "Missing", 1, "", "IP assignment/license", "CPA/attorney decide value and treatment."],
    ["Home office equipment", "Office equipment", "Adam", "", "", "", "", "Partial", 1, "", "Owner contribution / reimbursement", "Desk, chair, lighting, office-only equipment."],
  ]);
assetsSheet.getRange("J5:J84").formulas = Array.from({ length: 80 }, (_, index) => {
  const row = index + 5;
  return [`=IF(OR(G${row}="",I${row}=""),"",G${row}*I${row})`];
});
assetsSheet.getRange("E5:G84").format.numberFormat = "$#,##0.00";
assetsSheet.getRange("I5:I84").format.numberFormat = "0%";
assetsSheet.getRange("J5:J84").format.numberFormat = "$#,##0.00";

const home = workbook.worksheets.add("Home Office");
title(home, "Home Office Worksheet", "CPA decides simplified vs actual method. This sheet collects measurements and cost evidence; qualifying exclusive business use still matters.", 8);
setWidths(home, [34, 16, 18, 18, 18, 24, 28, 28]);
writeBlock(home, 1, 4, [
  ["Input", "Value", "Source / Evidence", "Notes"],
  ["Exclusive business area sq ft", "", "Measurement / photo", ""],
  ["Total home sq ft", "", "Lease, appraisal, measurement", ""],
  ["Business-use %", "=IFERROR(B5/B6,0)", "Formula", ""],
  ["Months eligible in year", "", "Start date / usage log", ""],
  ["Simplified method estimate", "=IFERROR(MIN(B5,300)*5*B8/12,0)", "Formula", "CPA decides whether to elect."],
]);
styleTable(home, "A4:D4", "A4:D9");
home.getRange("B7").format.numberFormat = "0.0%";
home.getRange("B9").format.numberFormat = "$#,##0.00";

writeBlock(home, 1, 12, [
  ["Expense", "Annual Amount", "Direct / Indirect", "Business %", "Potential Business Allocation", "Evidence Link", "CPA Notes"],
  ["Rent or mortgage interest", "", "Indirect", "=B7", "", "", ""],
  ["Utilities", "", "Indirect", "=B7", "", "", ""],
  ["Internet", "", "Indirect", "", "", "", "Use CPA-approved business-use allocation."],
  ["Insurance", "", "Indirect", "=B7", "", "", ""],
  ["Repairs - direct office", "", "Direct", "100%", "", "", ""],
  ["Repairs - whole home", "", "Indirect", "=B7", "", "", ""],
  ["Office-only supplies", "", "Direct", "100%", "", "", ""],
  ["Other", "", "", "", "", "", ""],
  ["Total actual-method evidence", "=SUM(B13:B20)", "", "", "=SUM(E13:E20)", "", ""],
]);
styleTable(home, "A12:G12", "A12:G21");
home.getRange("E13:E20").formulas = Array.from({ length: 8 }, (_, index) => {
  const row = index + 13;
  return [`=IF(OR(B${row}="",D${row}=""),"",B${row}*D${row})`];
});
home.getRange("B13:B21").format.numberFormat = "$#,##0.00";
home.getRange("D13:D20").format.numberFormat = "0.0%";
home.getRange("E13:E21").format.numberFormat = "$#,##0.00";

const ip = workbook.worksheets.add("IP & Software");
title(ip, "Software And IP Schedule", "Track robot-control software and ADA-related code before attorney and CPA review.", 10);
setWidths(ip, [26, 22, 22, 22, 28, 26, 18, 18, 22, 34]);
addTable(ip, 1, 4,
  ["Software / Repo", "Current Owner", "Transfer Type", "Included Scope", "Dependencies / Licenses", "Business Purpose", "Proposed Value", "Value Support", "CPA Treatment", "Attorney Notes"],
  [
    ["Robot-control software", "Adam", "Assignment or license", "Robot runtime, control modules, docs", "TBD", "Run ADA robot and demos", "", "", "Review", ""],
    ["ADA-related Zero code", "Adam / ADA", "Assignment or license", "Company OS, finance workflow, integrations", "TBD", "Operate ADA AI LLC", "", "", "Review", ""],
  ]);
ip.getRange("G5:G44").format.numberFormat = "$#,##0.00";

const cpa = workbook.worksheets.add("CPA Packet");
title(cpa, "CPA Packet Tracker", "Use this sheet as the packet cover before the first CPA setup consult and each monthly close.", 7);
setWidths(cpa, [30, 18, 26, 16, 30, 36, 24]);
addTable(cpa, 1, 4,
  ["Packet Item", "Owner", "Evidence", "Status", "Decision Needed", "Location", "Notes"],
  [
    ["EIN confirmation", "Finance", "CP 575 / confirmation letter", "Missing", "Confirm legal name and responsible party", "Secure company docs", ""],
    ["Operating agreement", "Legal", "Signed PDF", "Missing", "Confirm banking authorization", "Legal docs", ""],
    ["Bank/card decision log", "Finance", "Completed template", "Ready", "Choose bank/card", "templates/bank-card-decision-log.md", ""],
    ["P&L / transaction export", "Finance", "Transactions sheet", "Partial", "Bookkeeping method", "Transactions", ""],
    ["Subscription register", "Finance", "Subscriptions sheet", "Ready", "Categories and business use", "Subscriptions", ""],
    ["Asset register", "Asset", "Assets sheet + photos", "Partial", "Transfer method and basis", "Assets", ""],
    ["Home-office worksheet", "Finance", "Measurements and receipts", "Partial", "Simplified vs actual method", "Home Office", ""],
    ["IP/software schedule", "Legal", "IP schedule", "Ready", "Assignment/license and tax treatment", "IP & Software", ""],
    ["CPA decisions list", "Finance", "Agenda", "Ready", "All open decisions", "templates/cpa-setup-agenda.md", ""],
  ]);

const sources = workbook.worksheets.add("Sources");
title(sources, "Source Links And Guardrails", "Official sources and implementation guardrails for the setup workbook.", 5);
setWidths(sources, [28, 64, 52, 24, 36]);
addTable(sources, 1, 4,
  ["Source", "URL", "Why it matters", "Last checked", "Workbook control"],
  [
    ["IRS EIN", "https://www.irs.gov/businesses/employer-identification-number", "EIN is free through IRS and used for banking/tax identity.", "2026-05-05", "EIN setup step"],
    ["IRS EIN assistant", "https://www.irs.gov/businesses/small-businesses-self-employed/get-an-employer-identification-number", "Direct online application path.", "2026-05-05", "EIN setup step"],
    ["IRS SMLLC", "https://www.irs.gov/businesses/small-businesses-self-employed/single-member-limited-liability-companies", "Default disregarded-entity treatment.", "2026-05-05", "Operating stance"],
    ["SBA bank account", "https://www.sba.gov/business-guide/launch-your-business/open-business-bank-account", "Bank account checklist after EIN.", "2026-05-05", "Bank packet"],
    ["IRS Pub. 583", "https://www.irs.gov/publications/p583", "Separate records and supporting documents.", "2026-05-05", "Books and receipts"],
    ["IRS Pub. 334", "https://www.irs.gov/publications/p334", "Ordinary and necessary business expense baseline.", "2026-05-05", "Transaction categories"],
    ["IRS Pub. 587", "https://www.irs.gov/publications/p587", "Home-office simplified/actual evidence.", "2026-05-05", "Home Office"],
    ["IRS Pub. 551", "https://www.irs.gov/publications/p551", "Basis, FMV, and unpaid labor guardrail.", "2026-05-05", "Assets"],
    ["IRS Pub. 946", "https://www.irs.gov/publications/p946", "Depreciation and placed-in-service concepts.", "2026-05-05", "Assets"],
    ["FinCEN BOI FAQ", "https://www.fincen.gov/index.php/boi-faqs", "Current domestic-entity federal BOI exemption note.", "2026-05-05", "Legal guardrail"],
    ["Experian", "https://www.experian.com/blogs/ask-experian/do-business-credit-cards-show-up-on-a-personal-credit-report/", "Business card personal-credit reporting overview.", "2026-05-05", "Card policy log"],
  ]);

const sheetsToRender = [
  ["Dashboard", "A1:T18"],
  ["Setup Checklist", "A1:I16"],
  ["Transactions", "A1:J14"],
  ["Subscriptions", "A1:I14"],
  ["Assets", "A1:L13"],
  ["Home Office", "A1:G22"],
  ["IP & Software", "A1:J9"],
  ["CPA Packet", "A1:G14"],
  ["Sources", "A1:E16"],
];

const dashboardCheck = await workbook.inspect({
  kind: "table",
  range: "Dashboard!A4:C11",
  include: "values,formulas",
});
const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
});

for (const [sheetName, range] of sheetsToRender) {
  const preview = await workbook.render({ sheetName, range, autoCrop: "all", scale: 1 });
  await fs.writeFile(path.join(previewDir, `${sheetName.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}.png`), new Uint8Array(await preview.arrayBuffer()));
}

const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(outputPath);

console.log(JSON.stringify({
  outputPath,
  dashboardRows: dashboardCheck.text?.split("\n").length ?? 0,
  formulaErrorMatches: errors.text?.trim() ? errors.text.trim().split("\n").length : 0,
  renderedSheets: sheetsToRender.length,
}, null, 2));
