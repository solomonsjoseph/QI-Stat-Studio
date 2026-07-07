from __future__ import annotations

def _test_used(result: dict | None) -> str:
    return str((result or {}).get("test_used") or "")


def _freq_bucket(freq: str | None) -> str:
    value = (freq or "ME").upper()
    if value.startswith("D"):
        return "day"
    if value.startswith("W"):
        return "week"
    if value.startswith("Y") or value.startswith("A"):
        return "year"
    return "month"


def _spss_date_bucket(params: dict) -> str:
    dc = params.get("date_col", "encounter_date")
    bucket = _freq_bucket(params.get("freq"))
    if bucket == "day":
        expression = f"XDATE.DATE({dc})"
    elif bucket == "week":
        expression = f"XDATE.WEEK({dc})"
    elif bucket == "year":
        expression = f"XDATE.YEAR({dc})"
    else:
        expression = f"XDATE.MONTH({dc})"
    return f"* Derive date_bucket from {dc} using {bucket} frequency.\nCOMPUTE date_bucket={expression}.\nEXECUTE."


def _sas_date_bucket(params: dict) -> str:
    dc = params.get("date_col", "encounter_date")
    bucket = _freq_bucket(params.get("freq"))
    return f"intnx('{bucket}', {dc}, 0, 'b') AS date_bucket FORMAT=date9."


def generate_r_code(template: str, params: dict, result: dict | None = None) -> str:
    if template == "descriptive_summary":
        cols = ", ".join(f'"{c}"' for c in params.get("value_cols", [])) or '"var1"'
        grp = params.get("group_col")
        group_line = f"group_by({grp}) %>% " if grp else ""
        return (
            f"library(dplyr)\n"
            f"df %>% {group_line}\n"
            f"  summarise(across(c({cols}),\n"
            f"    list(n=~sum(!is.na(.)), mean=~mean(., na.rm=TRUE), sd=~sd(., na.rm=TRUE), median=~median(., na.rm=TRUE))))"
        )

    if template == "before_after_mean":
        gc = params.get("group_col", "period")
        vc = params.get("value_col", "value")
        pre = params.get("pre_val", "pre")
        post = params.get("post_val", "post")
        used = _test_used(result)
        if used == "Two-sample t-test":
            test_line = "t.test(pre, post)"
            comment = "# Runtime decision: Two-sample t-test"
        elif used == "Wilcoxon rank-sum test":
            test_line = "wilcox.test(pre, post)"
            comment = "# Runtime decision: Wilcoxon rank-sum test"
        else:
            test_line = "wilcox.test(pre, post)  # or t.test(pre, post) if normal"
            comment = "# Runtime decision unavailable; choose test after assumption checks"
        return (
            f"{comment}\n"
            f"pre <- df[df${gc} == '{pre}', '{vc}']\n"
            f"post <- df[df${gc} == '{post}', '{vc}']\n"
            f"{test_line}"
        )

    if template == "before_after_pct":
        gc = params.get("group_col", "period")
        oc = params.get("outcome_col", "outcome")
        pre = params.get("pre_val", "pre")
        post = params.get("post_val", "post")
        used = _test_used(result)
        if used == "Fisher's exact test":
            test_line = "fisher.test(ct)"
            comment = "# Runtime decision: Fisher's exact test"
        elif used == "Chi-square test":
            test_line = "chisq.test(ct)"
            comment = "# Runtime decision: Chi-square test"
        else:
            test_line = "chisq.test(ct)  # use fisher.test(ct) if expected counts are < 5"
            comment = "# Runtime decision unavailable; choose Fisher vs chi-square from expected counts"
        return (
            f"{comment}\n"
            f"sub <- df[df${gc} %in% c('{pre}', '{post}'), ]\n"
            f"ct <- table(sub${gc}, sub${oc})\n"
            f"{test_line}"
        )

    if template == "run_chart":
        dc = params.get("date_col", "encounter_date")
        vc = params.get("value_col", "value")
        return (
            f"library(ggplot2)\n"
            f"df${dc} <- as.Date(df${dc})\n"
            f"med <- median(df${vc}, na.rm=TRUE)\n"
            f"ties <- sum(df${vc} == med, na.rm=TRUE)  # exclude median ties from run counts\n"
            f"# Trend signal: check for >=6 consecutive increases or decreases.\n"
            f"ggplot(df, aes(x={dc}, y={vc})) + geom_line() + geom_point() +\n"
            f"  geom_hline(yintercept=med, color='red', linetype='dashed')"
        )

    if template == "p_chart":
        dc = params.get("date_col", "encounter_date")
        nc = params.get("numerator_col", "outcome")
        denom = params.get("denominator_col")
        if denom:
            aggregate = f"summarise(num=sum({nc}, na.rm=TRUE), denom=sum({denom}, na.rm=TRUE))"
        else:
            aggregate = f"summarise(num=sum({nc}, na.rm=TRUE), denom=n())"
        return (
            f"library(dplyr)\n"
            f"df${dc} <- as.Date(df${dc})\n"
            f"monthly <- df %>% group_by(month=format({dc}, '%Y-%m')) %>% {aggregate}\n"
            f"monthly$p <- monthly$num / monthly$denom\n"
            f"pbar <- mean(monthly$p, na.rm=TRUE)\n"
            f"nbar <- mean(monthly$denom, na.rm=TRUE)\n"
            f"monthly$ucl <- pbar + 3*sqrt(pbar*(1-pbar)/nbar)\n"
            f"monthly$lcl <- pmax(0, pbar - 3*sqrt(pbar*(1-pbar)/nbar))"
        )

    if template == "u_c_chart":
        dc = params.get("date_col", "encounter_date")
        cc = params.get("count_col", "count")
        denom = params.get("denominator_col")
        if denom:
            return (
                f"library(dplyr)\n"
                f"df${dc} <- as.Date(df${dc})\n"
                f"monthly <- df %>% group_by(month=format({dc}, '%Y-%m')) %>% "
                f"summarise(cnt=sum({cc}, na.rm=TRUE), denom=sum({denom}, na.rm=TRUE))\n"
                f"monthly$rate <- monthly$cnt / monthly$denom\n"
                f"ubar <- mean(monthly$rate, na.rm=TRUE)\n"
                f"nbar <- mean(monthly$denom, na.rm=TRUE)\n"
                f"monthly$ucl <- ubar + 3*sqrt(ubar/nbar)\n"
                f"monthly$lcl <- pmax(0, ubar - 3*sqrt(ubar/nbar))"
            )
        return (
            f"library(dplyr)\n"
            f"df${dc} <- as.Date(df${dc})\n"
            f"monthly <- df %>% group_by(month=format({dc}, '%Y-%m')) %>% summarise(cnt=sum({cc}, na.rm=TRUE))\n"
            f"cbar <- mean(monthly$cnt, na.rm=TRUE)\n"
            f"monthly$ucl <- cbar + 3*sqrt(cbar)\n"
            f"monthly$lcl <- pmax(0, cbar - 3*sqrt(cbar))"
        )

    return f'# R code for template "{template}" not yet implemented.'


def generate_spss_code(template: str, params: dict, result: dict | None = None) -> str:
    if template == "descriptive_summary":
        cols = " ".join(params.get("value_cols", ["var1"]))
        grp = params.get("group_col")
        split = f"SORT CASES BY {grp}.\nSPLIT FILE BY {grp}.\n" if grp else ""
        return f"{split}DESCRIPTIVES VARIABLES={cols} /STATISTICS=MEAN STDDEV MEDIAN MIN MAX.\nSPLIT FILE OFF."

    if template == "before_after_mean":
        gc = params.get("group_col", "period")
        vc = params.get("value_col", "value")
        used = _test_used(result) or "Two-sample t-test"
        if used == "Wilcoxon rank-sum test":
            return f"* Runtime decision: {used}.\nNPAR TESTS /M-W={vc} BY {gc}(1 2)."
        return f"* Runtime decision: {used}.\nT-TEST GROUPS={gc}(1 2) /VARIABLES={vc} /CRITERIA=CI(.95)."

    if template == "before_after_pct":
        gc = params.get("group_col", "period")
        oc = params.get("outcome_col", "outcome")
        used = _test_used(result) or "Chi-square or Fisher's exact test depending on expected counts"
        exact = " /STATISTICS=CHISQ /METHOD=EXACT" if used == "Fisher's exact test" else " /STATISTICS=CHISQ"
        return f"* Runtime decision: {used}.\nCROSSTABS /TABLES={gc} BY {oc}{exact} /CELLS=COUNT ROW COLUMN."

    if template == "run_chart":
        dc = params.get("date_col", "encounter_date")
        vc = params.get("value_col", "value")
        return f"SORT CASES BY {dc}.\n* Median ties are excluded from run counts; trend signal is >=6 increases/decreases.\nGRAPH /LINE(SIMPLE)=VALUE({vc}) BY {dc}."

    if template == "p_chart":
        nc = params.get("numerator_col", "outcome")
        denom = params.get("denominator_col")
        bucket = _spss_date_bucket(params)
        denom_expr = f"SUM({denom})" if denom else "N"
        return f"{bucket}\nAGGREGATE /OUTFILE=* MODE=ADDVARIABLES /BREAK=date_bucket /num=SUM({nc}) /denom={denom_expr}.\nCOMPUTE p=num/denom.\n* Compute p-chart UCL/LCL from pbar and mean denominator."

    if template == "u_c_chart":
        cc = params.get("count_col", "count")
        denom = params.get("denominator_col")
        bucket = _spss_date_bucket(params)
        if denom:
            return f"{bucket}\nAGGREGATE /OUTFILE=* MODE=ADDVARIABLES /BREAK=date_bucket /cnt=SUM({cc}) /denom=SUM({denom}).\nCOMPUTE rate=cnt/denom.\n* Compute u-chart UCL/LCL from rate and denominator.\nEXECUTE."
        return f"{bucket}\nAGGREGATE /OUTFILE=* MODE=ADDVARIABLES /BREAK=date_bucket /cnt=SUM({cc}).\nCOMPUTE cbar=MEAN(cnt).\n* Compute c-chart UCL/LCL from cbar.\nEXECUTE."

    return f'* SPSS code for template "{template}" not yet implemented.'


def generate_sas_code(template: str, params: dict, result: dict | None = None) -> str:
    if template == "descriptive_summary":
        cols = " ".join(params.get("value_cols", ["var1"]))
        grp = params.get("group_col")
        class_stmt = f"CLASS {grp};\n" if grp else ""
        return f"PROC MEANS DATA=df N MEAN STD MEDIAN MIN MAX;\n{class_stmt}VAR {cols};\nRUN;"

    if template == "before_after_mean":
        gc = params.get("group_col", "period")
        vc = params.get("value_col", "value")
        used = _test_used(result) or "Two-sample t-test"
        proc = "PROC NPAR1WAY DATA=df WILCOXON;" if used == "Wilcoxon rank-sum test" else "PROC TTEST DATA=df;"
        return f"/* Runtime decision: {used}. */\n{proc}\nCLASS {gc};\nVAR {vc};\nRUN;"

    if template == "before_after_pct":
        gc = params.get("group_col", "period")
        oc = params.get("outcome_col", "outcome")
        used = _test_used(result) or "Chi-square or Fisher's exact test depending on expected counts"
        option = " / FISHER" if used == "Fisher's exact test" else " / CHISQ"
        return f"/* Runtime decision: {used}. */\nPROC FREQ DATA=df;\nTABLES {gc}*{oc}{option};\nRUN;"

    if template == "run_chart":
        dc = params.get("date_col", "encounter_date")
        vc = params.get("value_col", "value")
        return f"PROC SGPLOT DATA=df;\nSERIES X={dc} Y={vc};\nREFLINE median / AXIS=y;\n/* Exclude median ties from runs; trend is >=6 increases/decreases. */\nRUN;"

    if template == "p_chart":
        nc = params.get("numerator_col", "outcome")
        denom = params.get("denominator_col")
        denom_expr = f"sum({denom})" if denom else "count(*)"
        bucket = _sas_date_bucket(params)
        return f"PROC SQL; CREATE TABLE monthly AS SELECT {bucket}, sum({nc}) AS num, {denom_expr} AS denom FROM df GROUP BY date_bucket; QUIT;\nDATA monthly; SET monthly; p=num/denom; /* p-chart UCL/LCL use mean denominator */ RUN;"

    if template == "u_c_chart":
        cc = params.get("count_col", "count")
        denom = params.get("denominator_col")
        bucket = _sas_date_bucket(params)
        if denom:
            return f"PROC SQL; CREATE TABLE monthly AS SELECT {bucket}, sum({cc}) AS cnt, sum({denom}) AS denom FROM df GROUP BY date_bucket; QUIT;\nDATA monthly; SET monthly; rate=cnt/denom; /* u-chart */ RUN;"
        return f"PROC SQL; CREATE TABLE monthly AS SELECT {bucket}, sum({cc}) AS cnt FROM df GROUP BY date_bucket; QUIT;\nDATA monthly; SET monthly; cbar=mean(cnt); /* c-chart */ RUN;"

    return f'/* SAS code for template "{template}" not yet implemented. */'
