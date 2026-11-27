;; Read-only: writes the geometry of every entity in one block definition (local block coordinates).
;; For model space itself use dwg_inventory.lsp or the COM readers. Plain AutoLISP only (no vl-*).
;; Line format (tab-separated):  TYPE  layer  handle  data...
;;   LINE   x1,y1 x2,y2
;;   LWPOLYLINE closedflag  x,y,bulge x,y,bulge ...
;;   ARC    cx,cy r a0 a1          CIRCLE cx,cy r
;;   INSERT name x,y rot sx,sy
;;   HATCH  pattern  then raw boundary groups "code=value" until group 75
;;   TEXT/MTEXT x,y height text
;; Parsed by tools/geom.py (load). Call: (bg-dump "BLOCKNAME" "C:/path/out.tsv")
;; Comments must stay on their own lines: the runner strips them before sending the code inline.
(defun bg-f (v) (rtos v 2 4))
(defun bg-p (p) (strcat (bg-f (car p)) "," (bg-f (cadr p))))
(defun bg-dump (blk path / f e ed typ s r on)
  (setq f (open path "w" "utf8") e (cdr (assoc -2 (tblsearch "BLOCK" blk))))
  (while e
    (setq ed (entget e) typ (cdr (assoc 0 ed)))
    (setq s (strcat typ "\t" (cdr (assoc 8 ed)) "\t" (cdr (assoc 5 ed))))
    (cond
      ((= typ "LINE") (setq s (strcat s "\t" (bg-p (cdr (assoc 10 ed))) "\t" (bg-p (cdr (assoc 11 ed))))))
      ((= typ "LWPOLYLINE")
       (setq s (strcat s "\t" (itoa (logand 1 (cdr (assoc 70 ed))))))
       (foreach r ed
         (if (= (car r) 10) (setq s (strcat s "\t" (bg-p (cdr r)))))
         (if (= (car r) 42) (setq s (strcat s "," (bg-f (cdr r)))))))
      ((= typ "ARC") (setq s (strcat s "\t" (bg-p (cdr (assoc 10 ed))) "\t" (bg-f (cdr (assoc 40 ed))) "\t" (bg-f (cdr (assoc 50 ed))) "\t" (bg-f (cdr (assoc 51 ed))))))
      ((= typ "CIRCLE") (setq s (strcat s "\t" (bg-p (cdr (assoc 10 ed))) "\t" (bg-f (cdr (assoc 40 ed))))))
      ((= typ "INSERT") (setq s (strcat s "\t" (cdr (assoc 2 ed)) "\t" (bg-p (cdr (assoc 10 ed))) "\t" (bg-f (cdr (assoc 50 ed))) "\t" (bg-f (cdr (assoc 41 ed))) "," (bg-f (cdr (assoc 42 ed))))))
      ((member typ '("TEXT" "MTEXT")) (setq s (strcat s "\t" (bg-p (cdr (assoc 10 ed))) "\t" (bg-f (cdr (assoc 40 ed))) "\t" (cdr (assoc 1 ed)))))
      ((= typ "HATCH")
       (setq s (strcat s "\t" (cdr (assoc 2 ed))) on nil)
       (foreach r ed
         (cond
           ((= (car r) 91) (setq on T))
           ((= (car r) 75) (setq on nil))
           ((and on (member (car r) '(10 11)))
            (setq s (strcat s "\t" (itoa (car r)) "=" (bg-p (cdr r)))))
           ((and on (member (car r) '(92 72 73 93 40 42 50 51)))
            (setq s (strcat s "\t" (itoa (car r)) "=" (if (= (type (cdr r)) 'INT) (itoa (cdr r)) (bg-f (cdr r))))))))))
    (if (not (member typ '("VERTEX" "SEQEND" "ATTRIB"))) (write-line s f))
    (setq e (entnext e)))
  (write-line "#DONE" f)
  (close f)
  (princ))
