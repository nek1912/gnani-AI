import { useState } from "react";
import { Link } from "react-router-dom";
import { useI18n } from "@/lib/i18n/provider";
import { getGrievanceStatus, type GrievanceRecord } from "@/lib/data";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Reveal } from "@/components/motion/Reveal";

const ORDER = ["submitted", "in-review", "resolved"] as const;

export default function GrievanceStatusPage() {
  const { t } = useI18n();
  const [id, setId] = useState("");
  const [record, setRecord] = useState<GrievanceRecord | null>(null);
  const [searched, setSearched] = useState(false);

  function search() {
    setRecord(getGrievanceStatus(id.trim()) ?? null);
    setSearched(true);
  }

  const currentIdx = record ? ORDER.indexOf(record.status as (typeof ORDER)[number]) : -1;

  return (
    <div className="px-4 pt-8 pb-24 sm:px-6 md:px-12 md:pt-12">
      <Reveal trigger="load">
        <h1 className="text-[24px] font-medium tracking-tight text-[var(--ink)] sm:text-[30px] md:text-[40px]"
            style={{ fontFamily: "var(--font-display)" }}>{t("grievance.statusTitle")}</h1>
        <p className="mt-1 text-[var(--body)]">{t("grievance.statusSubtitle")}</p>
      </Reveal>

      <div className="mx-auto mt-6 sm:mt-8 max-w-2xl">
        <div className="rounded-[var(--radius-md)] border border-[var(--hairline)] bg-[var(--canvas)] p-4 shadow-[0_8px_32px_rgba(0,0,0,0.04)] sm:p-6 md:p-8">
          <div className="flex flex-col gap-2 sm:flex-row">
            <Input
              value={id}
              onChange={(e) => setId(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && search()}
              placeholder={t("common.enterComplaintId")}
              className="flex-1"
            />
            <Button onClick={search}>{t("common.findStatus")}</Button>
          </div>

          {searched && !record && (
            <div className="mt-6">
              <EmptyState title={t("grievance.notFound")} />
            </div>
          )}

          {record && (
            <Card className="mt-6 space-y-4 p-6">
              <div>
                <p className="font-mono text-sm font-semibold text-[var(--primary)]">{record.id}</p>
                <p className="mt-1 font-answer text-sm leading-relaxed text-[var(--ink)]">{record.details}</p>
              </div>

              <div className="flex items-center gap-2 border-t border-[var(--hairline)] pt-3">
                <Badge tone={currentIdx >= ORDER.length - 1 ? "success" : currentIdx >= 1 ? "warning" : "neutral"}>
                  {t(`status.${record.status}`)}
                </Badge>
              </div>

              <ol className="relative space-y-4 border-l border-[var(--hairline)] pl-4 pt-2">
                {ORDER.map((s, i) => {
                  const reached = i <= currentIdx;
                  return (
                    <li key={s} className="relative flex items-start gap-3">
                      <div
                        className={`absolute -left-[21px] top-1 h-3.5 w-3.5 rounded-full border-2 border-[var(--canvas)] ${
                          reached ? "bg-[var(--success)]" : "bg-[var(--hairline)]"
                        }`}
                      />
                      <div>
                        <p className={`text-sm font-medium ${reached ? "text-[var(--ink)]" : "text-[var(--muted-soft)]"}`}>
                          {t(`status.${s}`)}
                        </p>
                        {reached && record.timeline.find((tl) => tl.status === s) && (
                          <p className="text-xs text-[var(--body)]">{record.timeline.find((tl) => tl.status === s)!.timestamp}</p>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ol>
            </Card>
          )}

          <div className="mt-6 flex justify-center border-t border-[var(--hairline)] pt-5">
            <Link to="/grievance">
              <Button variant="secondary">{t("grievance.title")}</Button>
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
export { default as GrievanceStatusPage } from "./GrievanceStatusPage";
