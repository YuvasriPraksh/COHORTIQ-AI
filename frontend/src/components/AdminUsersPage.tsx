import { useState, type FormEvent } from "react";

import { ApiError } from "../api/client";
import {
  createStudent,
  createStaff,
  demoteToStudent,
  listUsers,
  resetUserPassword,
  runUserAction,
  updateUser,
  type UserAction,
} from "../api/cohortiq";
import {
  STAFF_EMAIL_DOMAIN,
  STUDENT_EMAIL_DOMAIN,
  type AdminUser,
  type AdminUserList,
  type UserProfile,
} from "../api/types";
import { useSession } from "../auth/session";
import { useResource } from "../hooks/useResource";
import { CohortPicker, useCohorts } from "./CohortPicker";
import { Notice } from "./Notice";
import { Badge, Card, ConfirmButton, EmptyState, Loaded, PageHeader, formatDate } from "./ui";

export function AdminUsersPage({ token, currentUser }: { token: string; currentUser: UserProfile }) {
  const { handleUnauthorized } = useSession();
  const cohortResource = useCohorts(true);
  const [roleFilter, setRoleFilter] = useState("");
  const [activeFilter, setActiveFilter] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionNotice, setActionNotice] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  // Create student form
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [batch, setBatch] = useState("");
  const [programme, setProgramme] = useState("");
  const [creationRole, setCreationRole] = useState<"student" | "staff">("student");
  const [creating, setCreating] = useState(false);

  // Inline edit / password reset
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editName, setEditName] = useState("");
  const [editBatch, setEditBatch] = useState("");
  const [editProgramme, setEditProgramme] = useState("");
  const [resetId, setResetId] = useState<number | null>(null);
  const [newPassword, setNewPassword] = useState("");

  const users = useResource<AdminUserList>(
    `admin-users:${roleFilter}:${activeFilter}`,
    (signal) => listUsers(token, { role: roleFilter || undefined, is_active: activeFilter || undefined, limit: 50 }, signal),
  );

  async function onCreate(event: FormEvent) {
    event.preventDefault();
    setActionError(null);
    setActionNotice(null);
    if (!email.trim() || !password || !batch.trim() || !programme.trim()) {
      setActionError("Enter email, password, admission batch, and programme to create the account.");
      return;
    }
    setCreating(true);
    try {
      const request = {
        email: email.trim(),
        password,
        admission_batch: batch.trim(),
        programme: programme.trim(),
        ...(fullName.trim() ? { full_name: fullName.trim() } : {}),
      };
      const created = creationRole === "staff"
        ? await createStaff(token, request)
        : await createStudent(token, request);
      setEmail("");
      setPassword("");
      setFullName("");
      setActionNotice(`Created ${creationRole} account ${created.email}.`);
      users.reload();
    } catch (caught) {
      if (caught instanceof ApiError && caught.kind === "unauthorized") {
        handleUnauthorized();
        return;
      }
      setActionError(caught instanceof ApiError ? caught.message : `Could not create ${creationRole} account.`);
    } finally {
      setCreating(false);
    }
  }

  async function runAction(id: number, action: UserAction, label: string) {
    setBusyId(id);
    setActionError(null);
    setActionNotice(null);
    try {
      await runUserAction(token, id, action);
      setActionNotice(`Completed: ${label}.`);
      users.reload();
    } catch (caught) {
      if (caught instanceof ApiError && caught.kind === "unauthorized") {
        handleUnauthorized();
        return;
      }
      setActionError(caught instanceof ApiError ? caught.message : `Could not ${label}.`);
    } finally {
      setBusyId(null);
    }
  }

  async function onSaveEdit(event: FormEvent, user: AdminUser) {
    event.preventDefault();
    setBusyId(user.id);
    setActionError(null);
    setActionNotice(null);
    try {
      await updateUser(token, user.id, {
        full_name: editName.trim() || null,
        admission_batch: editBatch.trim(),
        programme: editProgramme.trim(),
      });
      setEditingId(null);
      setActionNotice(`Updated profile for ${user.email}.`);
      users.reload();
    } catch (caught) {
      if (caught instanceof ApiError && caught.kind === "unauthorized") {
        handleUnauthorized();
        return;
      }
      setActionError(caught instanceof ApiError ? caught.message : "Could not update account.");
    } finally {
      setBusyId(null);
    }
  }

  async function onResetPassword(event: FormEvent, user: AdminUser) {
    event.preventDefault();
    setBusyId(user.id);
    setActionError(null);
    setActionNotice(null);
    try {
      await resetUserPassword(token, user.id, newPassword);
      setResetId(null);
      setNewPassword("");
      setActionNotice(`Password reset for ${user.email}.`);
      users.reload();
    } catch (caught) {
      if (caught instanceof ApiError && caught.kind === "unauthorized") {
        handleUnauthorized();
        return;
      }
      setActionError(caught instanceof ApiError ? caught.message : "Could not reset password.");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="stack">
      <PageHeader icon="users"
        title="User management"
        subtitle="Provision student and staff accounts, update cohort assignments, and manage account access. Administrators are securely provisioned outside public sign-up."
      />

      {actionError ? <Notice tone="error" title={actionError} /> : null}
      {actionNotice ? <Notice tone="info" title={actionNotice} /> : null}

      <Card title={`Create ${creationRole} account`}>
        <form onSubmit={onCreate} className="form" noValidate>
          <div className="field-row">
            <label className="field">
              <span>Account type</span>
              <select value={creationRole} onChange={(e) => setCreationRole(e.target.value as "student" | "staff")}>
                <option value="student">Student</option>
                <option value="staff">Staff / Teacher</option>
              </select>
            </label>
            <label className="field">
              <span>Email</span>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder={`name@${creationRole === "staff" ? STAFF_EMAIL_DOMAIN : STUDENT_EMAIL_DOMAIN}`}
              />
            </label>
            <label className="field">
              <span>Full name (optional)</span>
              <input value={fullName} onChange={(e) => setFullName(e.target.value)} />
            </label>
            <label className="field">
              <span>Password</span>
              <input type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
            </label>
          </div>
          <CohortPicker
            cohorts={cohortResource.cohorts}
            loading={cohortResource.loading}
            error={cohortResource.error}
            onRetry={cohortResource.reload}
            batch={batch}
            programme={programme}
            onChange={(b, p) => {
              setBatch(b);
              setProgramme(p);
            }}
          />
          <div>
            <button type="submit" className="button button--primary" disabled={creating}>
              {creating ? "Creating…" : `Create ${creationRole}`}
            </button>
          </div>
        </form>
      </Card>

      <Card
        title="Accounts"
        actions={
          <div className="filter-bar">
            <label className="filter-bar__field">
              <span className="visually-hidden">Filter by role</span>
              <select value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)}>
                <option value="">All roles</option>
                <option value="student">Students</option>
                <option value="staff">Staff</option>
                <option value="administrator">Administrators</option>
              </select>
            </label>
            <label className="filter-bar__field">
              <span className="visually-hidden">Filter by status</span>
              <select value={activeFilter} onChange={(e) => setActiveFilter(e.target.value)}>
                <option value="">All statuses</option>
                <option value="true">Active</option>
                <option value="false">Inactive</option>
              </select>
            </label>
            <button type="button" className="button button--ghost button--compact" onClick={users.reload}>
              Refresh
            </button>
          </div>
        }
      >
        <Loaded resource={users}>
          {(data) =>
            data.users.length === 0 ? (
              <EmptyState title="No matching accounts" />
            ) : (
              <div className="reg-list">
                {data.users.map((u) => {
                  const isSelf = u.id === currentUser.id;
                  const editing = editingId === u.id;
                  const resetting = resetId === u.id;
                  return (
                    <article key={u.id} className="reg-item">
                      <div className="reg-item__head">
                        <div>
                          <h3 className="reg-item__title">
                            {u.full_name || u.email} <span className="muted">({u.email})</span>
                          </h3>
                          <p className="reg-item__meta">
                            {u.role === "student" || u.role === "staff"
                              ? `Batch ${u.admission_batch ?? "—"} · ${u.programme ?? "—"}`
                              : "Administrator account"}
                            {" · "}Created {formatDate(u.created_at)}
                          </p>
                        </div>
                        <div className="reg-item__actions">
                          <Badge tone={u.role === "administrator" ? "caution" : "neutral"}>{u.role}</Badge>
                          <Badge tone={u.is_active ? "good" : "bad"}>{u.is_active ? "Active" : "Inactive"}</Badge>
                          {u.is_locked ? <Badge tone="bad">Locked</Badge> : null}
                        </div>
                      </div>

                      <div className="reg-item__admin">
                        <button
                          type="button"
                          className="button button--ghost button--compact"
                          onClick={() => {
                            if (editing) {
                              setEditingId(null);
                            } else {
                              setEditingId(u.id);
                              setEditName(u.full_name ?? "");
                              setEditBatch(u.admission_batch ?? "");
                              setEditProgramme(u.programme ?? "");
                            }
                          }}
                        >
                          {editing ? "Cancel edit" : "Edit cohort"}
                        </button>
                        {u.role === "student" || u.role === "staff" ? (
                          <button
                            type="button"
                            className="button button--ghost button--compact"
                            onClick={() => {
                              setResetId(resetting ? null : u.id);
                              setNewPassword("");
                            }}
                          >
                            {resetting ? "Cancel reset" : "Reset password"}
                          </button>
                        ) : null}
                        {u.is_locked ? (
                          <ConfirmButton
                            label="Unlock"
                            confirmLabel="Confirm unlock"
                            disabled={busyId === u.id}
                            onConfirm={() => void runAction(u.id, "unlock", `unlock ${u.email}`)}
                          />
                        ) : null}
                        {!isSelf && u.is_active ? (
                          <ConfirmButton
                            label="Deactivate"
                            confirmLabel="Confirm deactivate"
                            disabled={busyId === u.id}
                            onConfirm={() => void runAction(u.id, "deactivate", `deactivate ${u.email}`)}
                          />
                        ) : null}
                        {!isSelf && !u.is_active ? (
                          <ConfirmButton
                            label="Reactivate"
                            confirmLabel="Confirm reactivate"
                            disabled={busyId === u.id}
                            onConfirm={() => void runAction(u.id, "reactivate", `reactivate ${u.email}`)}
                          />
                        ) : null}
                        <ConfirmButton
                          label="Revoke sessions"
                          confirmLabel="Confirm revoke"
                          disabled={busyId === u.id}
                          onConfirm={() => void runAction(u.id, "revoke-sessions", `revoke sessions for ${u.email}`)}
                        />
                        {!isSelf && u.role === "administrator" ? (
                          <ConfirmButton
                            label="Demote to student"
                            confirmLabel="Confirm demote"
                            disabled={busyId === u.id}
                            onConfirm={() => {
                              setBusyId(u.id);
                              demoteToStudent(token, u.id)
                                .then(() => {
                                  setActionNotice(`Demoted ${u.email} to student.`);
                                  users.reload();
                                })
                                .catch((caught: unknown) =>
                                  setActionError(caught instanceof ApiError ? caught.message : "Could not demote."),
                                )
                                .finally(() => setBusyId(null));
                            }}
                          />
                        ) : null}
                      </div>

                      {editing ? (
                        <form onSubmit={(e) => void onSaveEdit(e, u)} className="form">
                          <div className="field-row">
                            <label className="field">
                              <span>Full name</span>
                              <input value={editName} onChange={(e) => setEditName(e.target.value)} />
                            </label>
                            <label className="field">
                              <span>Admission batch</span>
                              <input value={editBatch} onChange={(e) => setEditBatch(e.target.value)} />
                            </label>
                            <label className="field">
                              <span>Programme</span>
                              <input value={editProgramme} onChange={(e) => setEditProgramme(e.target.value)} />
                            </label>
                          </div>
                          <div>
                            <button type="submit" className="button button--primary button--compact" disabled={busyId === u.id}>
                              Save changes
                            </button>
                          </div>
                        </form>
                      ) : null}

                      {resetting ? (
                        <form onSubmit={(e) => void onResetPassword(e, u)} className="form">
                          <label className="field">
                            <span>New password for {u.email}</span>
                            <input
                              type="password"
                              autoComplete="new-password"
                              value={newPassword}
                              onChange={(e) => setNewPassword(e.target.value)}
                            />
                          </label>
                          <div>
                            <button type="submit" className="button button--primary button--compact" disabled={busyId === u.id}>
                              Set password
                            </button>
                          </div>
                        </form>
                      ) : null}
                    </article>
                  );
                })}
              </div>
            )
          }
        </Loaded>
      </Card>
    </div>
  );
}
