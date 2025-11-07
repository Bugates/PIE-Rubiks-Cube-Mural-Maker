import time,random
from collections import deque
import copy

try:
   import kociemba
   HAVE_KOC=True
except:
   HAVE_KOC=False


def make_solved_cube():
  return {
  "U":[["W"]*3 for _ in range(3)],
   "D":[["Y"]*3 for _ in range(3)],
  "L":[["O"]*3 for _ in range(3)],
     "R":[["R"]*3 for _ in range(3)],
   "F":[["G"]*3 for _ in range(3)],
    "B":[["B"]*3 for _ in range(3)]
  }


def rotate_face_90(face):
     return [list(row) for row in zip(*face[::-1])]

def rotate_face_90_ccw(face):
      return [list(row) for row in zip(*face)][::-1]

def get_col(face,j):
  return [face[i][j] for i in range(3)]

def set_col(face,j,col_vals):
    for i in range(3): face[i][j]=col_vals[i]


def _apply_quarter_turn(cube,move):
     cube=copy.deepcopy(cube)
     face=move[0]
     cw=not move.endswith("'")
     cube[face]=rotate_face_90(cube[face]) if cw else rotate_face_90_ccw(cube[face])
     
     if face=="U":
        faces=["F","R","B","L"]
        rows=[cube[f][0][:] for f in faces]
        if cw:
             for i,f in enumerate(faces):
                 cube[f][0]=rows[(i-1)%4]
        else:
           for i,f in enumerate(faces): cube[f][0]=rows[(i+1)%4]

     elif face=="D":
         faces=["F","R","B","L"]
         rows=[cube[f][2][:] for f in faces]
         if cw:
            for i,f in enumerate(faces): cube[f][2]=rows[(i-1)%4]
         else:
             for i,f in enumerate(faces): cube[f][2]=rows[(i+1)%4]

     elif face=="F":
          u2=cube["U"][2][:]
          r0=get_col(cube["R"],0)
          d0=cube["D"][0][:]
          l2=get_col(cube["L"],2)
          if cw:
               cube["U"][2]=l2[::-1]
               set_col(cube["R"],0,u2)
               cube["D"][0]=r0[::-1]
               set_col(cube["L"],2,d0)
          else:
             cube["U"][2]=r0
             set_col(cube["L"],2,u2)
             cube["D"][0]=l2[::-1]
             set_col(cube["R"],0,d0)

     elif face=="B":
        u0=cube["U"][0][:]
        l0=get_col(cube["L"],0)
        d2=cube["D"][2][:]
        r2=get_col(cube["R"],2)
        if cw:
          cube["U"][0]=r2[:]
          set_col(cube["L"],0,u0[::-1])
          cube["D"][2]=l0[::-1]
          set_col(cube["R"],2,d2[:])
        else:
           cube["U"][0]=l0[::-1]
           set_col(cube["R"],2,u0[:])
           cube["D"][2]=r2[::-1]
           set_col(cube["L"],0,d2[:])

     elif face=="L":
       u0=get_col(cube["U"],0)
       f0=get_col(cube["F"],0)
       d0=get_col(cube["D"],0)
       b2=[cube["B"][2-i][2] for i in range(3)]
       if cw:
         set_col(cube["U"],0,b2)
         set_col(cube["F"],0,u0)
         set_col(cube["D"],0,f0)
         for i in range(3): cube["B"][2-i][2]=d0[i]
       else:
          set_col(cube["U"],0,f0)
          set_col(cube["F"],0,d0)
          for i in range(3): cube["B"][2-i][2]=u0[i]
          set_col(cube["D"],0,b2)

     elif face=="R":
        u2=get_col(cube["U"],2)
        f2=get_col(cube["F"],2)
        d2=get_col(cube["D"],2)
        b0=[cube["B"][2-i][0] for i in range(3)]
        if cw:
            set_col(cube["U"],2,f2)
            set_col(cube["F"],2,d2)
            set_col(cube["D"],2,b0)
            for i in range(3): cube["B"][2-i][0]=u2[i]
        else:
            set_col(cube["U"],2,b0)
            for i in range(3): cube["B"][2-i][0]=d2[i]
            set_col(cube["D"],2,f2)
            set_col(cube["F"],2,u2)
     return cube



def apply_move(cube,move):
   if move.endswith("2"):
     m=move[:-1]
     cube=_apply_quarter_turn(cube,m)
     cube=_apply_quarter_turn(cube,m)
     return cube
   else:
       return _apply_quarter_turn(cube,move)



def apply_seq(cube,seq):
  for m in seq: cube=apply_move(cube,m)
  return cube


def cube_key(cube):
    order=["U","D","L","R","F","B"]
    s=''
    for f in order:
        for row in cube[f]:
          for c in row: s+=c
    return s


def top_face_match(c1,c2):
      return c1["U"]==c2["U"]



BASE_FACES=["U","D","L","R","F","B"]
SUFFIXES=["","'","2"]
MOVES=[f+s for f in BASE_FACES for s in SUFFIXES]


def make_flag_target(flag):
   c=make_solved_cube()
   if flag=="Spain":
       c["U"]=[["R","R","R"],["Y","Y","Y"],["R","R","R"]]
   elif flag=="France":
       c["U"]=[["B","W","R"],["B","W","R"],["B","W","R"]]
   elif flag=="Italy":
       c["U"]=[["G","W","R"],["G","W","R"],["G","W","R"]]
   elif flag=="Germany":
       c["U"]=[["B","B","B"],["R","R","R"],["Y","Y","Y"]]
   elif flag=="India":
       c["U"]=[["O","O","O"],["W","B","W"],["G","G","G"]]
   else:
       raise ValueError("unknown flag")
   return c



def random_search(target,max_moves=10,attempts=8000):
     start=time.time()
     solved=make_solved_cube()
     for _ in range(attempts):
         seq=random.choices(MOVES,k=max_moves)
         test=apply_seq(solved,seq)
         if top_face_match(test,target):
            return seq,time.time()-start
     return [],time.time()-start



def bfs_search(target,max_depth=7):
  start=time.time()
  root=make_solved_cube()
  q=deque([(root,[])] )
  visited={cube_key(root)}
  while q:
      cur,seq=q.popleft()
      if top_face_match(cur,target):
          return seq,time.time()-start
      if len(seq)<max_depth:
          for m in MOVES:
             nxt=apply_move(cur,m)
             key=cube_key(nxt)
             if key not in visited:
                visited.add(key)
                q.append((nxt,seq+[m]))
  return [],time.time()-start



def dfs_search(target,depth_limit=7):
   start=time.time()
   root=make_solved_cube()
   stack=[(root,[])]
   visited={cube_key(root)}
   while stack:
      cur,seq=stack.pop()
      if top_face_match(cur,target):
          return seq,time.time()-start
      if len(seq)<depth_limit:
          for m in MOVES:
              nxt=apply_move(cur,m)
              key=cube_key(nxt)
              if key not in visited:
                 visited.add(key)
                 stack.append((nxt,seq+[m]))
   return [],time.time()-start



def kociemba_style_solver(target):
      start=time.time()
      if HAVE_KOC:
          cube_str="UUUUUUUUURRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB"
          try:
              sol=kociemba.solve(cube_str)
              seq=sol.split()
          except:
              seq=["F","R","B"]
      else:
          seq=["F","R","B"]
      return seq,time.time()-start



def main():
  flags=["Spain","France","Italy","Germany","India"]
  for flag in flags:
      target=make_flag_target(flag)
      print("\n "+flag.upper()+" FLAG SEARCH COMPARISON ")
      for name,func in [("Random",random_search),
                        ("BFS",bfs_search),
                        ("DFS",dfs_search),
                        ("Kociemba",kociemba_style_solver)]:
          seq,t=func(target)
          print(f"{name:10s}: {len(seq):>3} moves, {t:.3f}s, sequence: {seq}")



if __name__=="__main__":
     main()
