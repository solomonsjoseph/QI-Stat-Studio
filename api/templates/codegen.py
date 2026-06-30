def generate_r_code(template: str, params: dict) -> str:
    if template == "descriptive_summary":
        cols = ", ".join(f'"{c}"' for c in params.get("value_cols", []))
        grp = params.get("group_col", "group")
        return (f'library(dplyr)\ndf <- read.csv("your_data.csv")\n'
                f'df |> group_by({grp}) |>\n'
                f'  summarise(across(c({cols}),\n'
                f'    list(n=~sum(!is.na(.)), mean=mean, sd=sd, median=median), na.rm=TRUE))')

    if template == "before_after_mean":
        gc = params.get("group_col", "period")
        vc = params.get("value_col", "value")
        pre = params.get("pre_val", "pre")
        post = params.get("post_val", "post")
        return (f'library(dplyr)\ndf <- read.csv("your_data.csv")\n'
                f'df${gc} <- trimws(tolower(df${gc}))\n'
                f'pre <- df[df${gc} == "{pre}", "{vc}"]\n'
                f'post <- df[df${gc} == "{post}", "{vc}"]\n'
                f'shapiro.test(pre); shapiro.test(post)\n'
                f'wilcox.test(pre, post)  # or t.test if normal')

    if template == "before_after_pct":
        gc = params.get("group_col", "period")
        oc = params.get("outcome_col", "outcome")
        pre = params.get("pre_val", "pre")
        post = params.get("post_val", "post")
        return (f'library(dplyr)\ndf <- read.csv("your_data.csv")\n'
                f'df${gc} <- trimws(tolower(df${gc}))\n'
                f'ct <- table(df[df${gc} %in% c("{pre}","{post}"), c("{gc}", "{oc}")])\n'
                f'chisq.test(ct)  # or fisher.test(ct) if expected < 5')

    if template == "run_chart":
        dc = params.get("date_col", "encounter_date")
        vc = params.get("value_col", "value")
        return (f'library(dplyr); library(ggplot2)\ndf <- read.csv("your_data.csv")\n'
                f'df${dc} <- as.Date(df${dc})\n'
                f'monthly <- df |> group_by(month=format({dc}, "%Y-%m")) |>\n'
                f'  summarise(mean_{vc}=mean({vc}, na.rm=TRUE))\n'
                f'med <- median(monthly$mean_{vc})\n'
                f'ggplot(monthly, aes(x=month, y=mean_{vc}, group=1)) + geom_line() + geom_point() +\n'
                f'  geom_hline(yintercept=med, color="red", linetype="dashed")')

    if template == "p_chart":
        dc = params.get("date_col", "encounter_date")
        nc = params.get("numerator_col", "outcome")
        return (f'library(dplyr); library(ggplot2)\ndf <- read.csv("your_data.csv")\n'
                f'df${dc} <- as.Date(df${dc})\n'
                f'monthly <- df |> group_by(month=format({dc}, "%Y-%m")) |>\n'
                f'  summarise(num=sum({nc},na.rm=TRUE), denom=n())\n'
                f'monthly$p <- monthly$num/monthly$denom\n'
                f'pbar <- mean(monthly$p); nbar <- mean(monthly$denom)\n'
                f'monthly$ucl <- pbar + 3*sqrt(pbar*(1-pbar)/nbar)\n'
                f'monthly$lcl <- pmax(0, pbar - 3*sqrt(pbar*(1-pbar)/nbar))')

    if template == "u_c_chart":
        dc = params.get("date_col", "encounter_date")
        cc = params.get("count_col", "count")
        return (f'library(dplyr)\ndf <- read.csv("your_data.csv")\n'
                f'df${dc} <- as.Date(df${dc})\n'
                f'monthly <- df |> group_by(month=format({dc}, "%Y-%m")) |>\n'
                f'  summarise(cnt=sum({cc},na.rm=TRUE))\n'
                f'cbar <- mean(monthly$cnt)\n'
                f'monthly$ucl <- cbar + 3*sqrt(cbar)\n'
                f'monthly$lcl <- pmax(0, cbar - 3*sqrt(cbar))')

    return f'# R code for template "{template}" not yet implemented.'


def generate_spss_code(template: str, params: dict) -> str:
    if template == "descriptive_summary":
        cols = " ".join(params.get("value_cols", ["var1"]))
        grp = params.get("group_col", "group")
        return (f'* Read data.\nGET FILE="your_data.sav".\n'
                f'SORT CASES BY {grp}.\n'
                f'SPLIT FILE LAYERED BY {grp}.\n'
                f'DESCRIPTIVES VARIABLES={cols}\n'
                f'  /STATISTICS=MEAN STDDEV MIN MAX.\n'
                f'SPLIT FILE OFF.')

    if template == "before_after_mean":
        gc = params.get("group_col", "period")
        vc = params.get("value_col", "value")
        pre = params.get("pre_val", "pre")
        post = params.get("post_val", "post")
        return (f'GET FILE="your_data.sav".\n'
                f'SELECT IF ({gc}="{pre}" OR {gc}="{post}").\n'
                f'T-TEST GROUPS={gc}("{pre}" "{post}")\n'
                f'  /VARIABLES={vc}\n'
                f'  /CRITERIA=CI(.95).')

    if template == "before_after_pct":
        gc = params.get("group_col", "period")
        oc = params.get("outcome_col", "outcome")
        pre = params.get("pre_val", "pre")
        post = params.get("post_val", "post")
        return (f'GET FILE="your_data.sav".\n'
                f'SELECT IF ({gc}="{pre}" OR {gc}="{post}").\n'
                f'CROSSTABS\n'
                f'  /TABLES={gc} BY {oc}\n'
                f'  /STATISTICS=CHISQ\n'
                f'  /CELLS=COUNT ROW COLUMN.')

    if template == "run_chart":
        dc = params.get("date_col", "encounter_date")
        vc = params.get("value_col", "value")
        return (f'GET FILE="your_data.sav".\n'
                f'* Aggregate to monthly mean.\n'
                f'AGGREGATE OUTFILE=* MODE=ADDVARIABLES\n'
                f'  /BREAK={dc}\n'
                f'  /mean_{vc}=MEAN({vc}).\n'
                f'GRAPH\n'
                f'  /LINE(SIMPLE)=VALUE({vc}) BY {dc}.')

    if template == "p_chart":
        dc = params.get("date_col", "encounter_date")
        nc = params.get("numerator_col", "outcome")
        return (f'GET FILE="your_data.sav".\n'
                f'* Aggregate numerator and denominator by period.\n'
                f'AGGREGATE OUTFILE=* MODE=ADDVARIABLES\n'
                f'  /BREAK={dc}\n'
                f'  /num=SUM({nc})\n'
                f'  /denom=N.\n'
                f'COMPUTE p=num/denom.\n'
                f'EXECUTE.\n'
                f'* Plot p-chart manually or use SPSS SPC add-on.')

    if template == "u_c_chart":
        dc = params.get("date_col", "encounter_date")
        cc = params.get("count_col", "count")
        return (f'GET FILE="your_data.sav".\n'
                f'AGGREGATE OUTFILE=* MODE=ADDVARIABLES\n'
                f'  /BREAK={dc}\n'
                f'  /cnt=SUM({cc}).\n'
                f'COMPUTE cbar=MEAN(cnt).\n'
                f'COMPUTE ucl=cbar + 3*SQRT(cbar).\n'
                f'COMPUTE lcl=MAX(0, cbar - 3*SQRT(cbar)).\n'
                f'EXECUTE.')

    return f'* SPSS code for template "{template}" not yet implemented.'


def generate_sas_code(template: str, params: dict) -> str:
    if template == "descriptive_summary":
        cols = " ".join(params.get("value_cols", ["var1"]))
        grp = params.get("group_col", "group")
        return (f'/* Read data */\n'
                f'PROC IMPORT DATAFILE="your_data.csv" OUT=mydata DBMS=CSV REPLACE;\n'
                f'  GETNAMES=YES;\n'
                f'RUN;\n\n'
                f'PROC MEANS DATA=mydata N MEAN STD MEDIAN;\n'
                f'  CLASS {grp};\n'
                f'  VAR {cols};\n'
                f'RUN;')

    if template == "before_after_mean":
        gc = params.get("group_col", "period")
        vc = params.get("value_col", "value")
        pre = params.get("pre_val", "pre")
        post = params.get("post_val", "post")
        return (f'PROC IMPORT DATAFILE="your_data.csv" OUT=mydata DBMS=CSV REPLACE;\n'
                f'  GETNAMES=YES;\nRUN;\n\n'
                f'DATA mydata; SET mydata;\n'
                f'  WHERE {gc} IN ("{pre}" "{post}");\n'
                f'RUN;\n\n'
                f'PROC TTEST DATA=mydata;\n'
                f'  CLASS {gc};\n'
                f'  VAR {vc};\n'
                f'RUN;')

    if template == "before_after_pct":
        gc = params.get("group_col", "period")
        oc = params.get("outcome_col", "outcome")
        pre = params.get("pre_val", "pre")
        post = params.get("post_val", "post")
        return (f'PROC IMPORT DATAFILE="your_data.csv" OUT=mydata DBMS=CSV REPLACE;\n'
                f'  GETNAMES=YES;\nRUN;\n\n'
                f'DATA mydata; SET mydata;\n'
                f'  WHERE {gc} IN ("{pre}" "{post}");\n'
                f'RUN;\n\n'
                f'PROC FREQ DATA=mydata;\n'
                f'  TABLES {gc}*{oc} / CHISQ FISHER;\n'
                f'RUN;')

    if template == "run_chart":
        dc = params.get("date_col", "encounter_date")
        vc = params.get("value_col", "value")
        return (f'PROC IMPORT DATAFILE="your_data.csv" OUT=mydata DBMS=CSV REPLACE;\n'
                f'  GETNAMES=YES;\nRUN;\n\n'
                f'PROC MEANS DATA=mydata NWAY;\n'
                f'  CLASS {dc};\n'
                f'  VAR {vc};\n'
                f'  OUTPUT OUT=monthly MEAN={vc}_mean;\n'
                f'RUN;\n\n'
                f'PROC SGPLOT DATA=monthly;\n'
                f'  SERIES X={dc} Y={vc}_mean;\n'
                f'  REFLINE median / AXIS=Y;\n'
                f'RUN;')

    if template == "p_chart":
        dc = params.get("date_col", "encounter_date")
        nc = params.get("numerator_col", "outcome")
        return (f'PROC IMPORT DATAFILE="your_data.csv" OUT=mydata DBMS=CSV REPLACE;\n'
                f'  GETNAMES=YES;\nRUN;\n\n'
                f'PROC MEANS DATA=mydata NWAY SUM N;\n'
                f'  CLASS {dc};\n'
                f'  VAR {nc};\n'
                f'  OUTPUT OUT=monthly SUM={nc}_sum N={nc}_n;\n'
                f'RUN;\n\n'
                f'DATA monthly;\n'
                f'  SET monthly;\n'
                f'  p = {nc}_sum / {nc}_n;\n'
                f'RUN;\n\n'
                f'PROC SHEWHART DATA=monthly;\n'
                f'  PCHART p*{dc} (n={nc}_n);\n'
                f'RUN;')

    if template == "u_c_chart":
        dc = params.get("date_col", "encounter_date")
        cc = params.get("count_col", "count")
        return (f'PROC IMPORT DATAFILE="your_data.csv" OUT=mydata DBMS=CSV REPLACE;\n'
                f'  GETNAMES=YES;\nRUN;\n\n'
                f'PROC MEANS DATA=mydata NWAY SUM;\n'
                f'  CLASS {dc};\n'
                f'  VAR {cc};\n'
                f'  OUTPUT OUT=monthly SUM={cc}_sum;\n'
                f'RUN;\n\n'
                f'PROC SHEWHART DATA=monthly;\n'
                f'  CCHART {cc}_sum*{dc};\n'
                f'RUN;')

    return f'/* SAS code for template "{template}" not yet implemented. */'
