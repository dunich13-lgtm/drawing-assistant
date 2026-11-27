;; Read-only DWG inventory dump. One tab-separated line per entity, for every block definition,
;; model space and every layout. Changes nothing in the drawing. Plain AutoLISP only (no vl-*).
;; Columns: owner  type  layer  handle  [INSERT: name x,y,z rot_rad sx,sy | TEXT/MTEXT/ATTRIB/ATTDEF: tag x,y,z height text
;;          | ACAD_TABLE: "" x,y,z rows cols | DIMENSION: "" defpoint measurement]
;; Owner is the block name, "*<layout>" for model/paper space (e.g. *Model), "*SUB" for attributes of model inserts.
;; Call: (di-dump "C:/path/out.tsv")
;; Comments must stay on their own lines: the runner strips them before sending the code inline.
(defun di-p (p) (if p (strcat (rtos (car p) 2 4) "," (rtos (cadr p) 2 4) "," (rtos (if (caddr p) (caddr p) 0.0) 2 4)) ""))
(defun di-r (ed k d) (if (assoc k ed) (rtos (cdr (assoc k ed)) 2 6) d))
(defun di-txt (ed / s) (setq s "") (foreach r ed (if (= (car r) 3) (setq s (strcat s (cdr r))))) (strcat s (if (assoc 1 ed) (cdr (assoc 1 ed)) "")))
(defun di-row (f own ed / typ s)
  (setq typ (cdr (assoc 0 ed)))
  (setq s (strcat own "\t" typ "\t" (cdr (assoc 8 ed)) "\t" (cdr (assoc 5 ed))))
  (cond
    ((= typ "INSERT")
     (setq s (strcat s "\t" (cdr (assoc 2 ed)) "\t" (di-p (cdr (assoc 10 ed))) "\t" (di-r ed 50 "0") "\t" (di-r ed 41 "1") "," (di-r ed 42 "1"))))
    ((member typ '("TEXT" "MTEXT" "ATTRIB" "ATTDEF"))
     (setq s (strcat s "\t" (if (and (member typ '("ATTRIB" "ATTDEF")) (assoc 2 ed)) (cdr (assoc 2 ed)) "") "\t" (di-p (cdr (assoc 10 ed))) "\t" (di-r ed 40 "0") "\t" (di-txt ed))))
    ((= typ "ACAD_TABLE")
     (setq s (strcat s "\t\t" (di-p (cdr (assoc 10 ed))) "\t" (if (assoc 91 ed) (itoa (cdr (assoc 91 ed))) "") "\t" (if (assoc 92 ed) (itoa (cdr (assoc 92 ed))) ""))))
    ((= typ "DIMENSION")
     (setq s (strcat s "\t\t" (di-p (cdr (assoc 10 ed))) "\t" (di-r ed 42 ""))))
  )
  (write-line s f))
(defun di-dump (path / f b e ed own n typ lay)
  (setq f (open path "w" "utf8") n 0)
  (setq b (tblnext "BLOCK" T))
  (while b
    (setq own (cdr (assoc 2 b)) e (cdr (assoc -2 b)))
    (while e
      (setq ed (entget e) typ (cdr (assoc 0 ed)))
      (if (not (member typ '("VERTEX" "SEQEND"))) (progn (di-row f own ed) (setq n (1+ n))))
      (setq e (entnext e)))
    (setq b (tblnext "BLOCK")))
  (setq e (entnext))
  (while e
    (setq ed (entget e) typ (cdr (assoc 0 ed)))
    (cond
      ((member typ '("VERTEX" "SEQEND")))
      ((= typ "ATTRIB") (di-row f "*SUB" ed) (setq n (1+ n)))
      (T (setq lay (if (assoc 410 ed) (cdr (assoc 410 ed)) "?")) (di-row f (strcat "*" lay) ed) (setq n (1+ n))))
    (setq e (entnext e)))
  (write-line (strcat "#DONE\t" (itoa n)) f)
  (close f)
  (princ (strcat "\nDWG inventory: " (itoa n) " entities written."))
  (princ))
