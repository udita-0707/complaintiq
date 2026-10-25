# M2 mapping review (checkpoint, step 3)

Aggregates only. Rows = cleaned narrative rows (after min_words and dedup): 1,253,594. Time-split cutoffs: train <= 2022-09-12, val <= 2023-05-05, test after.

## 1. Product classes: date coverage and split counts

| product_class | rows | first | last | train | val | test |
|---|---|---|---|---|---|---|
| Credit reporting or credit repair | 575,358 | 2015-03-19 | 2024-02-08 | 355,475 | 113,487 | 106,396 |
| Debt collection | 210,749 | 2015-03-19 | 2024-02-09 | 171,562 | 18,964 | 20,223 |
| Credit card or prepaid card | 132,212 | 2015-03-19 | 2024-02-08 | 97,133 | 16,090 | 18,989 |
| Mortgage | 112,186 | 2015-03-19 | 2024-02-09 | 95,851 | 8,488 | 7,847 |
| Checking or savings account | 99,066 | 2015-03-19 | 2024-02-08 | 65,957 | 16,000 | 17,109 |
| Student loan | 39,235 | 2015-03-19 | 2024-02-03 | 31,764 | 2,759 | 4,712 |
| Money transfer or virtual currency | 37,148 | 2015-03-19 | 2024-02-08 | 26,550 | 5,261 | 5,337 |
| Vehicle loan or lease | 27,376 | 2017-04-24 | 2024-02-06 | 18,719 | 4,264 | 4,393 |
| Payday, title, or personal loan | 19,706 | 2015-03-19 | 2024-02-07 | 14,593 | 2,385 | 2,728 |
| OTHER | 558 | 2015-03-26 | 2024-02-06 | 291 | 0 | 267 |

### Raw Product values and their class

| product | rows | first | last | train | val | test | product_class |
|---|---|---|---|---|---|---|---|
| Credit reporting, credit repair services, or other personal consumer reports | 493,581 | 2017-04-24 | 2023-08-25 | 327,846 | 113,487 | 52,248 | Credit reporting or credit repair |
| Debt collection | 210,749 | 2015-03-19 | 2024-02-09 | 171,562 | 18,964 | 20,223 | Debt collection |
| Mortgage | 112,186 | 2015-03-19 | 2024-02-09 | 95,851 | 8,488 | 7,847 | Mortgage |
| Credit card or prepaid card | 101,701 | 2017-04-24 | 2023-08-25 | 77,406 | 16,090 | 8,205 | Credit card or prepaid card |
| Checking or savings account | 84,449 | 2017-04-24 | 2024-02-08 | 51,340 | 16,000 | 17,109 | Checking or savings account |
| Credit reporting or other personal consumer reports | 54,148 | 2023-08-25 | 2024-02-08 | 0 | 0 | 54,148 | Credit reporting or credit repair |
| Student loan | 39,235 | 2015-03-19 | 2024-02-03 | 31,764 | 2,759 | 4,712 | Student loan |
| Money transfer, virtual currency, or money service | 35,668 | 2017-04-24 | 2024-02-08 | 25,070 | 5,261 | 5,337 | Money transfer or virtual currency |
| Credit card | 27,940 | 2015-03-19 | 2024-02-08 | 18,318 | 0 | 9,622 | Credit card or prepaid card |
| Credit reporting | 27,629 | 2015-03-19 | 2017-04-22 | 27,629 | 0 | 0 | Credit reporting or credit repair |
| Vehicle loan or lease | 27,376 | 2017-04-24 | 2024-02-06 | 18,719 | 4,264 | 4,393 | Vehicle loan or lease |
| Payday loan, title loan, or personal loan | 16,632 | 2017-04-24 | 2023-08-24 | 12,912 | 2,385 | 1,335 | Payday, title, or personal loan |
| Bank account or service | 14,617 | 2015-03-19 | 2017-04-22 | 14,617 | 0 | 0 | Checking or savings account |
| Prepaid card | 2,571 | 2015-03-23 | 2024-02-06 | 1,409 | 0 | 1,162 | Credit card or prepaid card |
| Payday loan | 1,681 | 2015-03-19 | 2017-04-21 | 1,681 | 0 | 0 | Payday, title, or personal loan |
| Money transfers | 1,467 | 2015-03-19 | 2017-04-21 | 1,467 | 0 | 0 | Money transfer or virtual currency |
| Payday loan, title loan, personal loan, or advance loan | 1,393 | 2023-08-25 | 2024-02-07 | 0 | 0 | 1,393 | Payday, title, or personal loan |
| Other financial service | 291 | 2015-03-26 | 2017-04-20 | 291 | 0 | 0 | OTHER |
| Debt or credit management | 267 | 2023-08-25 | 2024-02-06 | 0 | 0 | 267 | OTHER |
| Virtual currency | 13 | 2015-04-06 | 2017-04-03 | 13 | 0 | 0 | Money transfer or virtual currency |

## 2. Issue top-N coverage

| top_n | overall | train | val | test |
|---|---|---|---|---|
| 10 | 0.718 | 0.695 | 0.781 | 0.763 |
| 15 | 0.796 | 0.786 | 0.831 | 0.813 |
| 20 | 0.846 | 0.835 | 0.878 | 0.864 |
| 25 | 0.886 | 0.875 | 0.917 | 0.906 |
| 30 | 0.918 | 0.909 | 0.942 | 0.937 |
| 40 | 0.963 | 0.958 | 0.979 | 0.974 |

## 3. Issue classes (top_n = 30): date coverage and split counts

| issue_class | rows | first | last | train | val | test |
|---|---|---|---|---|---|---|
| Incorrect information on your report | 272,069 | 2015-03-19 | 2024-02-07 | 180,269 | 46,150 | 45,650 |
| Problem with a company's investigation into an existing problem | 169,084 | 2015-03-19 | 2024-02-07 | 109,403 | 32,313 | 27,368 |
| Improper use of your report | 121,487 | 2015-03-19 | 2024-02-08 | 55,489 | 33,299 | 32,699 |
| Attempts to collect debt not owed | 96,571 | 2015-03-19 | 2024-02-09 | 77,961 | 9,218 | 9,392 |
| OTHER | 85,395 | 2015-03-19 | 2024-02-08 | 65,874 | 9,415 | 10,106 |
| Managing an account | 58,097 | 2015-03-19 | 2024-02-07 | 39,509 | 9,142 | 9,446 |
| Trouble during payment process | 53,009 | 2015-03-19 | 2024-02-08 | 44,415 | 4,308 | 4,286 |
| Written notification about debt | 39,959 | 2015-03-19 | 2024-02-07 | 32,552 | 3,317 | 4,090 |
| Problem with a purchase shown on your statement | 31,546 | 2015-03-19 | 2024-02-08 | 22,454 | 4,256 | 4,836 |
| Struggling to pay mortgage | 30,077 | 2015-03-19 | 2024-02-07 | 25,956 | 2,271 | 1,850 |
| Dealing with your lender or servicer | 28,072 | 2015-03-19 | 2024-01-26 | 21,973 | 2,296 | 3,803 |
| Took or threatened to take negative or legal action | 22,531 | 2015-03-19 | 2024-02-07 | 17,935 | 2,309 | 2,287 |
| Communication tactics | 22,497 | 2015-03-19 | 2024-02-08 | 18,869 | 1,641 | 1,987 |
| False statements or representation | 22,249 | 2015-03-19 | 2024-02-06 | 18,161 | 2,053 | 2,035 |
| Applying for a mortgage or refinancing an existing mortgage | 16,327 | 2015-03-19 | 2024-02-05 | 14,517 | 964 | 846 |
| Fraud or scam | 14,733 | 2015-03-20 | 2024-02-06 | 10,128 | 2,423 | 2,182 |
| Other features, terms, or problems | 13,809 | 2017-04-24 | 2024-02-06 | 9,655 | 1,939 | 2,215 |
| Closing an account | 12,338 | 2017-04-24 | 2024-02-07 | 7,469 | 2,277 | 2,592 |
| Fees or interest | 12,304 | 2017-04-24 | 2024-02-07 | 8,742 | 1,611 | 1,951 |
| Problem when making payments | 11,677 | 2017-04-24 | 2024-02-08 | 8,461 | 1,571 | 1,645 |
| Unable to get your credit report or credit score | 11,553 | 2015-03-19 | 2024-02-06 | 8,870 | 1,490 | 1,193 |
| Getting a credit card | 11,098 | 2017-04-24 | 2024-02-06 | 6,852 | 2,091 | 2,155 |
| Problem with a lender or other company charging your account | 10,392 | 2017-04-24 | 2024-02-08 | 6,041 | 2,021 | 2,330 |
| Closing on a mortgage | 10,268 | 2015-03-19 | 2024-02-09 | 8,977 | 701 | 590 |
| Closing your account | 9,509 | 2015-03-19 | 2024-02-06 | 7,144 | 1,069 | 1,296 |
| Managing the loan or lease | 9,483 | 2017-04-24 | 2024-02-05 | 6,549 | 1,387 | 1,547 |
| Opening an account | 8,849 | 2017-04-24 | 2024-02-08 | 5,762 | 1,493 | 1,594 |
| Struggling to repay your loan | 8,509 | 2015-03-19 | 2024-02-03 | 7,626 | 262 | 621 |
| Trouble using your card | 8,020 | 2017-04-24 | 2024-02-06 | 5,350 | 1,047 | 1,623 |
| Problem caused by your funds being low | 7,566 | 2015-03-19 | 2024-02-07 | 5,495 | 988 | 1,083 |
| Advertising and marketing, including promotional offers | 7,380 | 2015-03-19 | 2024-02-07 | 5,576 | 837 | 967 |
| Threatened to contact someone or share information improperly | 6,942 | 2015-03-19 | 2024-01-29 | 6,084 | 426 | 432 |
| Problem with fraud alerts or security freezes | 6,275 | 2017-04-27 | 2024-02-06 | 4,914 | 597 | 764 |
| Unauthorized transactions or other transaction problem | 3,919 | 2015-04-03 | 2024-01-22 | 2,863 | 516 | 540 |

### Harmonized issues with zero training rows (forced to OTHER)

- Charged upfront or unexpected fees
- Didn't provide services promised
- Issue where my lender is my school
- Issue with income share agreement
- Issues with repayment
- Problems receiving the advance
- Trouble accessing funds in your mobile or digital wallet
- Unauthorized withdrawals or charges
- Unexpected fees

### Merged raw issues (old/new names)

| issue | harmonized | rows | first | last |
|---|---|---|---|---|
| Problem with a credit reporting company's investigation into an existing problem | Problem with a company's investigation into an existing problem | 150,086 | 2017-04-24 | 2023-08-24 |
| Incorrect information on credit report | Incorrect information on your report | 18,529 | 2015-03-19 | 2017-04-22 |
| Cont'd attempts collect debt not owed | Attempts to collect debt not owed | 15,931 | 2015-03-19 | 2017-04-21 |
| Loan servicing, payments, escrow account | Trouble during payment process | 14,543 | 2015-03-19 | 2017-04-21 |
| Loan modification,collection,foreclosure | Struggling to pay mortgage | 10,662 | 2015-03-19 | 2017-04-21 |
| Dealing with my lender or servicer | Dealing with your lender or servicer | 7,782 | 2015-03-19 | 2017-04-21 |
| Disclosure verification of debt | Written notification about debt | 6,957 | 2015-03-19 | 2017-04-21 |
| Account opening, closing, or management | Managing an account | 6,224 | 2015-03-19 | 2017-04-22 |
| Credit reporting company's investigation | Problem with a company's investigation into an existing problem | 4,994 | 2015-03-19 | 2017-04-21 |
| Application, originator, mortgage broker | Applying for a mortgage or refinancing an existing mortgage | 3,688 | 2015-03-19 | 2017-04-21 |
| Deposits and withdrawals | Managing an account | 3,361 | 2015-03-19 | 2017-04-21 |
| Trouble using the card | Trouble using your card | 3,086 | 2017-04-25 | 2024-02-06 |
| Billing disputes | Problem with a purchase shown on your statement | 2,990 | 2015-03-19 | 2017-04-21 |
| Can't repay my loan | Struggling to repay your loan | 2,981 | 2015-03-19 | 2017-04-21 |
| Taking/threatening an illegal action | Took or threatened to take negative or legal action | 2,780 | 2015-03-19 | 2017-04-21 |
| Improper contact or sharing of info | Threatened to contact someone or share information improperly | 2,701 | 2015-03-19 | 2017-04-21 |
| Settlement process and costs | Closing on a mortgage | 2,228 | 2015-03-19 | 2017-04-21 |
| Problems caused by my funds being low | Problem caused by your funds being low | 2,037 | 2015-03-19 | 2017-04-21 |
| Unable to get credit report/credit score | Unable to get your credit report or credit score | 1,998 | 2015-03-19 | 2017-04-21 |
| Problem with a company's investigation into an existing issue | Problem with a company's investigation into an existing problem | 1,629 | 2017-04-24 | 2024-01-30 |
| Using a debit or ATM card | Managing an account | 1,577 | 2015-03-19 | 2017-04-21 |
| Closing/Cancelling account | Closing your account | 1,393 | 2015-03-19 | 2017-04-21 |
| Credit decision / Underwriting | Applying for a mortgage or refinancing an existing mortgage | 1,267 | 2015-03-19 | 2017-04-20 |
| Improper use of my credit report | Improper use of your report | 1,227 | 2015-03-19 | 2017-04-20 |
| Credit monitoring or identity protection | Credit monitoring or identity theft protection services | 881 | 2015-03-19 | 2017-04-21 |
| Advertising and marketing | Advertising and marketing, including promotional offers | 818 | 2015-03-19 | 2017-04-21 |
| Charged fees or interest I didn't expect | Charged fees or interest you didn't expect | 721 | 2015-03-19 | 2017-04-21 |
| Identity theft protection or other monitoring services | Credit monitoring or identity theft protection services | 678 | 2017-04-24 | 2024-02-01 |
| Unauthorized transactions/trans. issues | Unauthorized transactions or other transaction problem | 529 | 2015-04-03 | 2017-04-21 |
| Repossession | Vehicle was repossessed or sold the vehicle | 515 | 2023-08-25 | 2024-02-05 |
| Other transaction issues | Other transaction problem | 464 | 2015-03-19 | 2017-04-20 |
| Can't contact lender | Can't contact lender or servicer | 327 | 2015-03-19 | 2017-04-14 |
| Electronic communications | Communication tactics | 226 | 2023-08-25 | 2024-02-05 |
| Received a loan I didn't apply for | Received a loan you didn't apply for | 192 | 2015-03-22 | 2017-04-19 |
| Can't stop charges to bank account | Can't stop withdrawals from your bank account | 154 | 2015-03-23 | 2017-04-20 |
| Payment to acct not credited | Loan payment wasn't credited to your account | 120 | 2015-03-24 | 2017-04-19 |
| Charged bank acct wrong day or amt | Money was taken from your bank account on the wrong day or for the wrong amount | 99 | 2015-04-08 | 2017-04-14 |
| Adding money | Problem adding money | 88 | 2015-04-09 | 2017-04-11 |
| Applied for loan/did not receive money | Was approved for a loan, but didn't receive the money | 68 | 2015-03-30 | 2017-04-18 |
| Customer service/Customer relations | Customer service / Customer relations | 55 | 2015-04-23 | 2017-04-04 |
| Was approved for a loan, but didn't receive money | Was approved for a loan, but didn't receive the money | 34 | 2017-07-17 | 2023-12-08 |
| Unexpected/Other fees | Unexpected or other fees | 22 | 2015-03-26 | 2017-04-05 |
| Overdraft, savings or rewards features | Overdraft, savings, or rewards features | 16 | 2015-03-27 | 2017-01-07 |
| Problem with an overdraft | Problem with overdraft | 4 | 2017-07-16 | 2022-04-21 |

## 4. Severity list: rows per entry and resulting HIGH rate

| issue | rows | train | val | test |
|---|---|---|---|---|
| Fraud or scam | 14,733 | 10,128 | 2,423 | 2,182 |
| Identity theft / Fraud / Embezzlement | 1,667 | 1,667 | 0 | 0 |
| Received a loan you didn't apply for | 477 | 353 | 56 | 68 |
| Received a loan I didn't apply for | 192 | 192 | 0 | 0 |
| Problem with fraud alerts or security freezes | 6,275 | 4,914 | 597 | 764 |
| Unauthorized transactions or other transaction problem | 3,390 | 2,334 | 516 | 540 |
| Unauthorized transactions/trans. issues | 529 | 529 | 0 | 0 |
| Unauthorized withdrawals or charges | 35 | 0 | 0 | 35 |
| Took or threatened to take negative or legal action | 19,751 | 15,155 | 2,309 | 2,287 |
| Taking/threatening an illegal action | 2,780 | 2,780 | 0 | 0 |
| Threatened to contact someone or share information improperly | 4,241 | 3,383 | 426 | 432 |
| Improper contact or sharing of info | 2,701 | 2,701 | 0 | 0 |
| Communication tactics | 22,271 | 18,869 | 1,641 | 1,761 |
| Electronic communications | 226 | 0 | 0 | 226 |

| split | rows | high_rate | severity_rule | monetary_rule | untimely_rule |
|---|---|---|---|---|---|
| test | 188,001 | 0.093 | 0.044 | 0.042 | 0.010 |
| train | 877,895 | 0.137 | 0.072 | 0.052 | 0.021 |
| val | 187,698 | 0.086 | 0.042 | 0.038 | 0.009 |
| all | 1,253,594 | 0.123 | 0.063 | 0.048 | 0.018 |
