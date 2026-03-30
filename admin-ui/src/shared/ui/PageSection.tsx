import { ReactNode } from "react";

type Props = {
  title: string;
  description?: string;
  actions?: ReactNode;
  children?: ReactNode;
};

export function PageSection({ title, description, actions, children }: Props) {
  return (
    <section className="page-panel">
      <header className="page-panel-head">
        <div className="page-panel-title-wrap">
          <h2 className="page-panel-title">{title}</h2>
          {description ? <p className="page-panel-description">{description}</p> : null}
        </div>
        {actions ? <div className="page-panel-actions">{actions}</div> : null}
      </header>
      <div className="page-panel-body">{children}</div>
    </section>
  );
}
